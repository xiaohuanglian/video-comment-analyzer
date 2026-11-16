"""Hold the collection browser open until the user has logged in."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from api.services.outreach.reply_automation import (  # noqa: E402
    BILI_PROFILE_DIR,
    _fetch_account_info,
    _find_chromium_executable,
)


async def main() -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(BILI_PROFILE_DIR),
            executable_path=_find_chromium_executable(),
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.bilibili.com", wait_until="commit", timeout=90000)
            for _ in range(300):
                cookies = await context.cookies("https://www.bilibili.com")
                cookie = "; ".join(
                    f"{item['name']}={item['value']}"
                    for item in cookies
                    if item.get("name") and item.get("value")
                )
                if "SESSDATA=" in cookie and "bili_jct=" in cookie:
                    account = await asyncio.to_thread(_fetch_account_info, cookie)
                    if account.get("mid"):
                        print(json.dumps({"ok": True, "account": account}, ensure_ascii=False), flush=True)
                        return
                await asyncio.sleep(3)
            raise RuntimeError("等待登录超时")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
