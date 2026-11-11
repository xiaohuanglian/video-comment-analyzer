# -*- coding: utf-8 -*-
"""JSON 文件存储的统一底座：加锁读改写 + 原子写 + 损坏不静默。

为什么要有这个模块（2026-11-11 审计）：
项目里原先有 4 套各自实现的 JSON 持久化（`topics/store.py`、
`routers/topics.py`、`publish_log.py`、`reply_automation.AutomationStore`），
每一套都踩了同样的三个坑：

1. **无锁**：`load()` → 改 → `save()` 之间只要有一次 `await`（LLM 调用、
   浏览器发送、`to_thread`），并发请求就会互相覆盖。实测 20 并发
   `add_many` 最终只落 3 条。
2. **非原子写**：`path.write_text(...)` 写到一半崩溃/断电，文件就残缺。
3. **损坏即静默清空**：`except JSONDecodeError: return []` 把「文件坏了」
   和「还没有数据」当成同一件事。下一次保存就会用空列表覆盖历史——
   对回复队列来说，这意味着 `processed_comment_ids` 丢失，
   已回复过的用户会被重新回复一遍。

这里把三件事一次做对：**同一把锁保护读改写、写走 tmp+os.replace、
损坏时备份现场并抛错而不是返回空**。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, TypeVar

T = TypeVar("T")


class JsonStoreCorruption(RuntimeError):
    """文件存在但无法解析：**绝不当作空数据**，必须让人知道。"""

    def __init__(self, path: Path, backup: Optional[Path], detail: str):
        self.path = path
        self.backup = backup
        self.detail = detail
        super().__init__(
            f"数据文件损坏，已保留现场：{path}"
            + (f"（备份：{backup}）" if backup else "（备份失败）")
            + f"；原因：{detail}"
        )


#: 全局锁表：同一个真实路径共用一把锁，跨模块也共用。
_locks: Dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock_for(path: Path | str) -> threading.RLock:
    """取某个文件路径对应的可重入锁（进程内）。"""
    try:
        key = str(Path(path).resolve())
    except OSError:
        key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def atomic_write_text(path: Path, text: str) -> None:
    """原子写：先写同目录临时文件，再 os.replace 顶替，读者永远看不到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _quarantine(path: Path) -> Optional[Path]:
    """把损坏文件改名留存，返回备份路径。备份成功后才能安全地重写。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        os.replace(path, backup)
        return backup
    except OSError:
        return None


def read_json(
    path: Path,
    *,
    default: Any,
    expect: Optional[type] = None,
    tolerate_corruption: bool = False,
) -> Any:
    """读 JSON。

    - 文件不存在 → 返回 default（这是真的「还没有数据」）
    - 文件存在但解析失败 → **默认抛 JsonStoreCorruption**，并已把坏文件
      改名留存；只有显式 `tolerate_corruption=True` 才降级为 default
      （仅用于「读挂了也不该拦住主流程」的旁路，如成本台账展示）。
    """
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else default
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        backup = _quarantine(path) if path.exists() else None
        if tolerate_corruption:
            return default
        raise JsonStoreCorruption(path, backup, f"{type(exc).__name__}: {exc}") from exc

    if expect is not None and not isinstance(data, expect):
        return default
    return data


def write_json(path: Path, payload: Any, *, indent: int = 1) -> None:
    """原子写 JSON（调用方应已持有 `lock_for(path)`）。"""
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent))


class JsonListStore(Generic[T]):
    """list[dict] 形状的 JSON 存储：加锁读改写 + 原子写 + 损坏不静默。"""

    def __init__(
        self,
        path: Path | Callable[[], Path],
        *,
        max_items: Optional[int] = None,
        indent: int = 1,
    ) -> None:
        self._path = path
        self.max_items = max_items
        self.indent = indent

    @property
    def path(self) -> Path:
        return self._path() if callable(self._path) else self._path

    @property
    def lock(self) -> threading.RLock:
        return lock_for(self.path)

    def load(self, *, tolerate_corruption: bool = False) -> List[T]:
        data = read_json(
            self.path,
            default=[],
            expect=list,
            tolerate_corruption=tolerate_corruption,
        )
        return [row for row in data if isinstance(row, dict)]

    def save(self, rows: Iterable[T]) -> None:
        items = list(rows)
        if self.max_items is not None:
            items = items[-self.max_items :]
        with self.lock:
            write_json(self.path, items, indent=self.indent)

    def read_modify_write(self, mutate: Callable[[List[T]], Any]) -> Any:
        """在锁内完成「读 → 改 → 写」，await 一律不要放在这里。

        返回 `mutate` 的返回值；`mutate` 直接改传入的列表即可。
        """
        with self.lock:
            rows = self.load()
            result = mutate(rows)
            self.save(rows)
            return result

    def append(self, row: T) -> List[T]:
        def _mutate(rows: List[T]) -> List[T]:
            rows.append(row)
            return rows

        return self.read_modify_write(_mutate)

    def remove_where(self, predicate: Callable[[T], bool]) -> int:
        def _mutate(rows: List[T]) -> int:
            kept = [row for row in rows if not predicate(row)]
            removed = len(rows) - len(kept)
            rows[:] = kept
            return removed

        return self.read_modify_write(_mutate)

    def file_version(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
        except OSError:
            return {"mtime_ns": 0, "size": 0}
        return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
