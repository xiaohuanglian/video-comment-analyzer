"""Local, single-window launcher. Never terminates an unknown process on the port."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_step(command: list[str], label: str, cwd: Path = ROOT) -> None:
    print(f"\n{label}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def port_in_use(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def health_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_when_ready(process: subprocess.Popen, url: str) -> None:
    for _ in range(120):
        if process.poll() is not None:
            return
        if health_ready(url):
            print(f"\n启动成功！正在打开 {url}\n使用期间请保持此窗口打开。停止工具请按 Ctrl+C。", flush=True)
            webbrowser.open(url)
            return
        time.sleep(1)
    print(f"\n启动较慢，请查看上方错误；就绪后可手动打开 {url}", flush=True)


def frontend_fingerprint() -> str:
    """Git pulls must rebuild stale assets without relying on file timestamps."""
    frontend = ROOT / "web_react"
    sources = [p for folder in ("src", "public") for p in (frontend / folder).rglob("*") if p.is_file()]
    sources += [frontend / name for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json")]
    digest = hashlib.sha256()
    for path in sorted(sources):
        if path.is_file():
            digest.update(path.relative_to(frontend).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    os.chdir(ROOT)
    # Load before reading PORT; preserve explicit environment overrides.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    try:
        port = int(os.environ.get("PORT", "8766"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("启动失败：PORT 需要是 1–65535 之间的整数。请联系维护者检查 .env。")
        return 1
    url = f"http://127.0.0.1:{port}"
    if port_in_use(port):
        print(f"端口 {port} 正在使用中。若工具已启动，请使用原窗口；否则请联系维护者。\n本次没有停止任何已有进程。")
        return 1
    uv = shutil.which("uv")
    if not uv:
        print("未找到 uv，请按 README 中的首次安装说明安装后重试。")
        return 1
    dist = ROOT / "web_react" / "dist" / "index.html"
    fingerprint = frontend_fingerprint()
    stamp = dist.parent / ".source-fingerprint"
    current = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    if not dist.is_file() or current != fingerprint:
        npm = shutil.which("npm")
        if not npm:
            print("首次启动或代码更新后需要 Node.js 22.12+（或 24.0+）构建新界面。请安装后重新打开启动文件。")
            return 1
        run_step([npm, "ci"], "[1/3] 正在准备新版界面依赖，请稍候…", ROOT / "web_react")
        run_step([npm, "run", "build"], "[2/3] 正在准备工作台界面…", ROOT / "web_react")
        stamp.write_text(fingerprint, encoding="utf-8")
    print(f"\n[3/3] 正在启动评论工作台：{url}", flush=True)
    process = subprocess.Popen(
        [uv, "run", "python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
        cwd=ROOT,
    )
    threading.Thread(target=open_when_ready, args=(process, url), daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\n正在停止工具…", flush=True)
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print("\n准备失败：请检查网络和上方错误，保留窗口内容交给维护者。修复后重新双击启动。")
        raise SystemExit(exc.returncode) from exc
