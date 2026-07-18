import asyncio
import re
import subprocess
import signal
import os
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from ..schemas import CrawlerStartRequest, LogEntry
from .crawl_progress import (
    count_records_in_file,
    count_final_session_comments,
    count_session_comment_progress,
    resolve_comments_file,
    snapshot_comment_files,
)
from .operation_guard import operation_coordinator


PROGRESS_CACHE_SECONDS = 120


class CrawlerManager:
    """Crawler process manager"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.status = "idle"
        self.started_at: Optional[datetime] = None
        self.current_config: Optional[CrawlerStartRequest] = None
        self._progress_baseline: int = 0
        self._progress_file_snapshot: dict[str, int] = {}
        self._progress_cache: Optional[dict] = None
        self._progress_cache_at: Optional[datetime] = None
        self._log_id = 0
        self._logs: List[LogEntry] = []
        self._read_task: Optional[asyncio.Task] = None
        self._stopped_by_user: bool = False
        self._last_result: Optional[dict] = None
        # Project root directory
        self._project_root = Path(__file__).parent.parent.parent
        # Log queue - for pushing to WebSocket
        self._log_queue: Optional[asyncio.Queue] = None

    @property
    def logs(self) -> List[LogEntry]:
        return self._logs

    def get_log_queue(self) -> asyncio.Queue:
        """Get or create log queue"""
        if self._log_queue is None:
            self._log_queue = asyncio.Queue()
        return self._log_queue

    def _create_log_entry(self, message: str, level: str = "info") -> LogEntry:
        """Create log entry"""
        self._log_id += 1
        entry = LogEntry(
            id=self._log_id,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message
        )
        self._logs.append(entry)
        # Keep last 500 logs
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
        return entry

    async def _push_log(self, entry: LogEntry):
        """Push log to queue"""
        if self._log_queue is not None:
            try:
                self._log_queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def _parse_log_level(self, line: str) -> str:
        """Parse log level"""
        line_upper = line.upper()
        if "ERROR" in line_upper or "FAILED" in line_upper:
            return "error"
        elif "WARNING" in line_upper or "WARN" in line_upper:
            return "warning"
        elif "SUCCESS" in line_upper or "完成" in line or "成功" in line:
            return "success"
        elif "DEBUG" in line_upper:
            return "debug"
        return "info"

    async def start(self, config: CrawlerStartRequest) -> bool:
        """Start crawler process"""
        async with self._lock:
            if self.process and self.process.poll() is None:
                return False
            if not await operation_coordinator.try_acquire("crawl"):
                return False

            # Clear old logs
            self._logs = []
            self._log_id = 0
            self._stopped_by_user = False
            self._last_result = None

            # Clear pending queue (don't replace object to avoid WebSocket broadcast coroutine holding old queue reference)
            if self._log_queue is None:
                self._log_queue = asyncio.Queue()
            else:
                try:
                    while True:
                        self._log_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            # Build command line arguments
            try:
                cmd = self._build_command(config)
            except Exception:
                await operation_coordinator.release("crawl")
                raise

            # Log start information
            entry = self._create_log_entry(f"Starting crawler: {' '.join(cmd)}", "info")
            await self._push_log(entry)

            try:
                # Start subprocess
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(self._project_root),
                    env={
                        **os.environ,
                        "PYTHONUNBUFFERED": "1",
                        "VC_CRAWLER_COOKIES": config.cookies or "",
                    }
                )

                self.status = "running"
                self.started_at = datetime.now()
                self.current_config = config
                self._progress_cache = None
                self._progress_cache_at = None
                self._progress_file_snapshot = snapshot_comment_files(self._project_root, config)
                self._progress_baseline = self._measure_progress_baseline(config)

                entry = self._create_log_entry(
                    f"Crawler started on platform: {config.platform.value}, type: {config.crawler_type.value}",
                    "success"
                )
                await self._push_log(entry)

                # Start log reading task
                self._read_task = asyncio.create_task(self._read_output())

                return True
            except Exception as e:
                self.status = "error"
                entry = self._create_log_entry(f"Failed to start crawler: {str(e)}", "error")
                await self._push_log(entry)
                await operation_coordinator.release("crawl")
                return False

    async def stop(self) -> bool:
        """Stop crawler process"""
        async with self._lock:
            if not self.process or self.process.poll() is not None:
                return False

            self.status = "stopping"
            self._stopped_by_user = True
            entry = self._create_log_entry("Sending SIGTERM to crawler process...", "warning")
            await self._push_log(entry)

            try:
                self.process.send_signal(signal.SIGTERM)

                # Wait for graceful exit (up to 15 seconds)
                for _ in range(30):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.5)

                # If still not exited, force kill
                if self.process.poll() is None:
                    entry = self._create_log_entry("Process not responding, sending SIGKILL...", "warning")
                    await self._push_log(entry)
                    self.process.kill()

                entry = self._create_log_entry("Crawler process terminated", "info")
                await self._push_log(entry)

            except Exception as e:
                entry = self._create_log_entry(f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(entry)

            exit_code = self.process.returncode if self.process else -1
            await self._finalize_task(exit_code)

            # Cancel log reading task
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None

            return True

    def _repair_stale_status(self) -> None:
        """If the subprocess already exited but status was not finalized, repair it."""
        if self.status not in {"running", "stopping"}:
            return
        if self.process is None or self.process.poll() is None:
            return
        exit_code = self.process.returncode if self.process.returncode is not None else -1
        if self._last_result is None:
            self._last_result = self._build_task_result(exit_code)
        self.status = "idle"
        self._stopped_by_user = False
        operation_coordinator.repair_stale("crawl")

    def get_status(self, refresh_progress: bool = False) -> dict:
        """Get current status"""
        self._repair_stale_status()
        progress = self._get_progress(refresh_progress=refresh_progress)
        payload = {
            "status": self.status,
            "platform": self.current_config.platform.value if self.current_config else None,
            "crawler_type": self.current_config.crawler_type.value if self.current_config else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": None,
            "comments_crawled": progress.get("crawled"),
            "comments_target": progress.get("target"),
            "progress_updated_at": progress.get("updated_at"),
            "result_kind": None,
            "result_title": None,
            "result_message": None,
            "finished_at": None,
        }
        if self._last_result:
            payload.update(self._last_result)
            if payload["error_message"] is None and self._last_result.get("result_kind") == "error":
                payload["error_message"] = self._last_result.get("result_message")
        return payload

    def _recent_log_messages(self, limit: int = 80) -> list[str]:
        return [getattr(entry, "message", "") or "" for entry in self._logs[-limit:]]

    def _find_last_error_reason(self, messages: list[str]) -> Optional[str]:
        for message in reversed(messages):
            upper = message.upper()
            if "ERROR" in upper or "FAILED" in upper or "Traceback" in message:
                cleaned = message.strip()
                if cleaned.startswith("2026-") and " - " in cleaned:
                    cleaned = cleaned.split(" - ", 1)[-1]
                return cleaned[:240]
        return None

    def _build_task_result(self, exit_code: int) -> dict:
        messages = self._recent_log_messages()
        progress = self._get_progress(refresh_progress=True)
        crawled = progress.get("crawled")
        if self.current_config and self.started_at:
            crawled = count_final_session_comments(
                self._project_root,
                self.current_config,
                started_at=self.started_at,
                snapshot=self._progress_file_snapshot,
            )
            progress["crawled"] = crawled
            self._progress_cache = progress
        finished_at = datetime.now().isoformat()

        progress_text = f"已抓取 {crawled} 条评论" if crawled is not None else ""

        if self._stopped_by_user:
            return {
                "result_kind": "stopped",
                "result_title": "抓取已手动停止",
                "result_message": f"{progress_text or '任务已停止'}。如需完整数据，请重新提交视频链接。",
                "finished_at": finished_at,
            }

        if exit_code != 0:
            reason = self._find_last_error_reason(messages) or f"进程异常退出（退出码 {exit_code}）"
            return {
                "result_kind": "error",
                "result_title": "抓取异常中断",
                "result_message": f"{reason}。{progress_text}".strip("。"),
                "finished_at": finished_at,
                "error_message": reason,
            }

        partial_line = next((m for m in reversed(messages) if "Partial completion" in m), None)
        if partial_line:
            match = re.search(r"saved\s+(\d+)/(\d+)", partial_line)
            if match:
                saved_from_log, expected = match.groups()
                saved = crawled if crawled is not None else int(saved_from_log)
                detail = f"已抓取 {saved} 条（视频约 {expected} 条一级评论）"
            else:
                detail = progress_text or "评论未抓全"
            return {
                "result_kind": "partial",
                "result_title": "抓取未完成",
                "result_message": (
                    f"{detail}。原因：B 站 API 提前返回结束，部分评论无法获取。"
                    "再次提交同一视频会自动从头重爬。"
                ),
                "finished_at": finished_at,
            }

        if any("Crawler finished with partial comments" in m for m in messages):
            return {
                "result_kind": "partial",
                "result_title": "抓取未完成",
                "result_message": (
                    f"{progress_text or '评论未抓全'}。原因：B 站 API 提前结束。"
                    "再次提交同一视频会自动从头重爬。"
                ),
                "finished_at": finished_at,
            }

        return {
            "result_kind": "completed",
            "result_title": "抓取已完成",
            "result_message": progress_text or "任务已成功结束，可在结果文件中查看 CSV。",
            "finished_at": finished_at,
        }

    async def _finalize_task(self, exit_code: int = 0) -> None:
        """Mark task finished and store user-facing result summary."""
        if self._last_result is not None:
            return

        self._last_result = self._build_task_result(exit_code)
        summary = self._last_result
        level = "success"
        if summary["result_kind"] in {"error", "stopped"}:
            level = "error" if summary["result_kind"] == "error" else "warning"
        elif summary["result_kind"] == "partial":
            level = "warning"

        entry = self._create_log_entry(
            f"[任务结束] {summary['result_title']}：{summary['result_message']}",
            level,
        )
        await self._push_log(entry)
        self.status = "idle"
        self._stopped_by_user = False
        await operation_coordinator.release("crawl")

    def clear_run_context(self) -> None:
        """Reset per-run metadata after the client has consumed the final result."""
        self.current_config = None
        self.started_at = None
        self._progress_baseline = 0
        self._progress_file_snapshot = {}
        self._progress_cache = None
        self._progress_cache_at = None
        self._last_result = None

    def _measure_progress_baseline(self, config: CrawlerStartRequest) -> int:
        if not config.enable_comments:
            return 0
        if config.split_by_video:
            return 0
        comment_file = resolve_comments_file(self._project_root, config)
        if not comment_file:
            return 0
        return count_records_in_file(comment_file, config.save_option.value)

    def _get_progress(self, refresh_progress: bool = False) -> dict:
        empty = {"crawled": None, "target": None, "updated_at": None}
        if not self.current_config:
            return empty
        if self.status not in {"running", "stopping"}:
            if self._progress_cache is not None:
                return self._progress_cache
            return empty

        now = datetime.now()
        if (
            not refresh_progress
            and self._progress_cache is not None
            and self._progress_cache_at is not None
            and (now - self._progress_cache_at).total_seconds() < PROGRESS_CACHE_SECONDS
        ):
            return self._progress_cache

        config = self.current_config
        crawled = None

        if config.enable_comments:
            if config.split_by_video:
                crawled = count_final_session_comments(
                    self._project_root,
                    config,
                    started_at=self.started_at,
                    snapshot=self._progress_file_snapshot,
                )
            else:
                comment_file = resolve_comments_file(
                    self._project_root,
                    config,
                    started_at=self.started_at,
                    snapshot=self._progress_file_snapshot,
                )
                if comment_file:
                    total = count_records_in_file(comment_file, config.save_option.value)
                    crawled = max(0, total - self._progress_baseline)

        result = {
            "crawled": crawled,
            "target": None,
            "updated_at": now.isoformat(),
        }
        self._progress_cache = result
        self._progress_cache_at = now
        return result

    def _build_command(self, config: CrawlerStartRequest) -> list:
        """Build main.py command line arguments"""
        cmd = ["uv", "run", "python", "main.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--lt", config.login_type.value])
        cmd.extend(["--type", config.crawler_type.value])
        cmd.extend(["--save_data_option", config.save_option.value])

        # Pass different arguments based on crawler type
        if config.crawler_type.value == "search" and config.keywords:
            cmd.extend(["--keywords", config.keywords])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            cmd.extend(["--specified_id", config.specified_ids])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            cmd.extend(["--creator_id", config.creator_ids])

        if config.start_page != 1:
            cmd.extend(["--start", str(config.start_page)])

        cmd.extend(["--get_comment", "true" if config.enable_comments else "false"])
        cmd.extend(["--get_sub_comment", "true" if config.enable_sub_comments else "false"])

        if config.max_notes_count is not None:
            cmd.extend(["--crawler_max_notes_count", str(config.max_notes_count)])

        if config.max_comments_count is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(config.max_comments_count)])

        if config.save_data_path:
            cmd.extend(["--save_data_path", config.save_data_path])

        cmd.extend(["--enable_safe_crawl", "true" if config.enable_safe_crawl else "false"])
        cmd.extend(["--split_by_video", "true" if config.split_by_video else "false"])
        cmd.extend(["--fresh_crawl", "true" if config.fresh_crawl else "false"])
        cmd.extend(["--crawler_max_sleep_sec", str(config.crawler_max_sleep_sec)])

        cmd.extend(["--headless", "true" if config.headless else "false"])

        return cmd

    async def _read_output(self):
        """Asynchronously read process output"""
        loop = asyncio.get_event_loop()

        try:
            while self.process and self.process.poll() is None:
                # Read a line in thread pool
                line = await loop.run_in_executor(
                    None, self.process.stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        level = self._parse_log_level(line)
                        entry = self._create_log_entry(line, level)
                        await self._push_log(entry)

            # Read remaining output
            if self.process and self.process.stdout:
                remaining = await loop.run_in_executor(
                    None, self.process.stdout.read
                )
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            level = self._parse_log_level(line)
                            entry = self._create_log_entry(line.strip(), level)
                            await self._push_log(entry)

            # Process ended
            if self.status == "running":
                exit_code = self.process.returncode if self.process else -1
                if exit_code == 0:
                    partial_hint = any(
                        "Partial completion" in (getattr(entry, "message", "") or "")
                        for entry in self.logs[-50:]
                    )
                    if partial_hint:
                        entry = self._create_log_entry(
                            "Crawler finished with partial comments — re-run the same video to continue",
                            "warning",
                        )
                        await self._push_log(entry)
                    else:
                        entry = self._create_log_entry("Crawler completed successfully", "success")
                        await self._push_log(entry)
                else:
                    entry = self._create_log_entry(f"Crawler exited with code: {exit_code}", "warning")
                    await self._push_log(entry)
                await self._finalize_task(exit_code)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            entry = self._create_log_entry(f"Error reading output: {str(e)}", "error")
            await self._push_log(entry)
            self.status = "error"
            await operation_coordinator.release("crawl")


# Global singleton
crawler_manager = CrawlerManager()
