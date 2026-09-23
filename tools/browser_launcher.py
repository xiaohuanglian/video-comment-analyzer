import os
import platform
import subprocess
import time
import socket
import signal
from typing import Optional, List, Tuple
import asyncio
from pathlib import Path

from tools import utils


class BrowserLauncher:
    """
    Browser launcher for detecting and launching user's Chrome/Edge browser
    Supports Windows and macOS systems
    """

    def __init__(self):
        self.system = platform.system()
        self.browser_process = None
        self.debug_port = None

    def detect_browser_paths(self) -> List[str]:
        """
        Detect available browser paths in system
        Returns list of browser paths sorted by priority
        """
        paths = []

        if self.system == "Windows":
            # Common Chrome/Edge installation paths on Windows
            possible_paths = [
                # Chrome paths
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                # Edge paths
                os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
                # Chrome Beta/Dev/Canary
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Beta\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Dev\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe"),
            ]
        elif self.system == "Darwin":  # macOS
            # Common Chrome/Edge installation paths on macOS
            possible_paths = [
                # Chrome paths
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                # Edge paths
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta",
                "/Applications/Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev",
                "/Applications/Microsoft Edge Canary.app/Contents/MacOS/Microsoft Edge Canary",
            ]
        else:
            # Linux and other systems
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome-beta",
                "/usr/bin/google-chrome-unstable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/microsoft-edge-beta",
                "/usr/bin/microsoft-edge-dev",
            ]

        # Check if path exists and is executable
        for path in possible_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                paths.append(path)

        return paths

    def find_available_port(self, start_port: int = 9222) -> int:
        """
        Find available port
        """
        port = start_port
        while port < start_port + 100:  # Try up to 100 ports
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                port += 1

        raise RuntimeError(f"Cannot find available port, tried {start_port} to {port-1}")

    def launch_browser(self, browser_path: str, debug_port: int, headless: bool = False,
                      user_data_dir: Optional[str] = None) -> subprocess.Popen:
        """
        Launch browser process
        """
        # Basic launch arguments
        args = [
            browser_path,
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=0.0.0.0",  # Allow remote access
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=TranslateUI",
            "--disable-ipc-flooding-protection",
            "--disable-hang-monitor",
            "--disable-prompt-on-repost",
            "--disable-sync",
            "--disable-breakpad",  # Avoid macOS Crashpad permission errors
            # Key anti-detection arguments
            "--disable-blink-features=AutomationControlled",  # Disable automation control flag
            "--exclude-switches=enable-automation",  # Exclude automation switch
            "--disable-infobars",  # Disable info bars
        ]
        # Linux/Docker often needs these; macOS shows a scary banner for --no-sandbox
        if self.system != "Darwin":
            args.extend(["--disable-dev-shm-usage", "--no-sandbox"])

        # Headless mode
        if headless:
            args.extend([
                "--headless=new",  # Use new headless mode
                "--disable-gpu",
            ])
        else:
            # Extra arguments for non-headless mode
            args.extend([
                "--start-maximized",  # Maximize window, more like real user
            ])

        # User data directory
        if user_data_dir:
            args.append(f"--user-data-dir={user_data_dir}")

        utils.logger.info(f"[BrowserLauncher] Launching browser: {browser_path}")
        utils.logger.info(f"[BrowserLauncher] Debug port: {debug_port}")
        utils.logger.info(f"[BrowserLauncher] Headless mode: {headless}")

        try:
            # On Windows, use CREATE_NEW_PROCESS_GROUP to prevent Ctrl+C from affecting subprocess
            if self.system == "Windows":
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid  # Create new process group
                )

            self.browser_process = process
            return process

        except Exception as e:
            utils.logger.error(f"[BrowserLauncher] Failed to launch browser: {e}")
            raise

    def wait_for_browser_ready(self, debug_port: int, timeout: int = 30) -> bool:
        """
        Wait for browser to be ready
        """
        utils.logger.info(f"[BrowserLauncher] Waiting for browser to be ready on port {debug_port}...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    result = s.connect_ex(('localhost', debug_port))
                    if result == 0:
                        utils.logger.info(f"[BrowserLauncher] Browser is ready on port {debug_port}")
                        return True
            except Exception:
                pass

            time.sleep(0.5)

        utils.logger.error(f"[BrowserLauncher] Browser failed to be ready within {timeout} seconds")
        return False

    def get_browser_info(self, browser_path: str) -> Tuple[str, str]:
        """
        Get browser info (name and version)
        """
        try:
            if "chrome" in browser_path.lower():
                name = "Google Chrome"
            elif "edge" in browser_path.lower() or "msedge" in browser_path.lower():
                name = "Microsoft Edge"
            elif "chromium" in browser_path.lower():
                name = "Chromium"
            else:
                name = "Unknown Browser"

            # Try to get version info
            try:
                result = subprocess.run([browser_path, "--version"],
                                      capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5)
                version = result.stdout.strip() if result.stdout else "Unknown Version"
            except:
                version = "Unknown Version"

            return name, version

        except Exception:
            return "Unknown Browser", "Unknown Version"

    def find_processes_using_user_data_dir(self, user_data_dir: str) -> List[int]:
        """PIDs of browser processes launched with the given --user-data-dir.

        Matches on the profile path so we only touch browsers this tool started;
        the user's own Chrome windows (different profile) are never affected.
        """
        if not user_data_dir or self.system == "Windows":
            return []
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"--user-data-dir={user_data_dir}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return []
        pids: List[int] = []
        for token in result.stdout.split():
            try:
                pid = int(token)
            except ValueError:
                continue
            if pid != os.getpid():
                pids.append(pid)
        return pids

    def kill_stale_browsers(self, user_data_dir: str) -> int:
        """Terminate leftover browsers holding the profile dir. Returns count."""
        stale = self.find_processes_using_user_data_dir(user_data_dir)
        if not stale:
            return 0
        utils.logger.warning(
            f"[BrowserLauncher] Found {len(stale)} leftover browser process(es) using {user_data_dir}; terminating"
        )
        for pid in stale:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(1.0)
        for pid in self.find_processes_using_user_data_dir(user_data_dir):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        return len(stale)

    def clear_stale_profile_locks(self, user_data_dir: str) -> None:
        """Remove Chromium singleton lock files left behind by a crashed run."""
        if not user_data_dir:
            return
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            path = os.path.join(user_data_dir, name)
            try:
                os.remove(path)
                utils.logger.info(f"[BrowserLauncher] Removed stale profile lock: {path}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                utils.logger.warning(f"[BrowserLauncher] Could not remove {path}: {exc}")

    def cleanup(self):
        """
        Cleanup resources, close browser process
        """
        if not self.browser_process:
            return

        process = self.browser_process

        if process.poll() is not None:
            utils.logger.info("[BrowserLauncher] Browser process already exited, no cleanup needed")
            self.browser_process = None
            return

        utils.logger.info("[BrowserLauncher] Closing browser process...")

        try:
            if self.system == "Windows":
                # First try normal termination
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    utils.logger.warning("[BrowserLauncher] Normal termination timeout, using taskkill to force kill")
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        check=False,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    process.wait(timeout=5)
            else:
                pgid = os.getpgid(process.pid)
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    utils.logger.info("[BrowserLauncher] Browser process group does not exist, may have exited")
                else:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        utils.logger.warning("[BrowserLauncher] Graceful shutdown timeout, sending SIGKILL")
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=5)

            utils.logger.info("[BrowserLauncher] Browser process closed")
        except Exception as e:
            utils.logger.warning(f"[BrowserLauncher] Error closing browser process: {e}")
        finally:
            self.browser_process = None
