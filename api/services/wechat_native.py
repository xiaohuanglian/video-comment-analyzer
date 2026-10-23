# -*- coding: utf-8 -*-
"""公众号文章原生采集(内置能力,不依赖任何外部工具)。

原理:mp.weixin.qq.com 文章页与合集(appmsgalbum)页均为公开可访问,
直接抓取解析:正文 HTML → 下载图片/视频 → 转 Markdown,落盘 data/wechat/。
视频三类嵌入均处理:① iframe.video_iframe(腾讯视频 vid,vv.video.qq.com getinfo 解析直链)
② 公众号原生 mp-common-mpvideo / data-mpvid(wxv_ id)——签名直链拿不到无头浏览器外的合法途径
(immersive_player 需微信 session、getvinfo 需 cKey),改用**无头浏览器捕获**:
普通 Chrome UA 下文章渲染为原生 <video>,点击播放后 currentSrc 即带签名的 mp4 直链
(mpvideo.qpic.cn,授权在 URL 参数里,但时效仅几分钟,捕获后立即下载);
③ 裸 <video> 标签(直接下 src;m3u8 不支持)。
版权提醒:仅供个人学习与素材研究,请勿搬运分发,尊重原作者。
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import random
import re
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WECHAT_DIR = PROJECT_ROOT / "data" / "wechat"
INDEX_FILE = WECHAT_DIR / "index.json"

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49"
)

# mpvideo.qpic.cn 防盗链校验 Fetch Metadata:必须像 <video> 元素一样发请求,否则 403
_VIDEO_DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "Referer": "https://mp.weixin.qq.com/",
    "Range": "bytes=0-",
    "Sec-Fetch-Dest": "video",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-origin",
}

_task_state: dict[str, Any] = {"running": False, "kind": "", "total": 0, "done": 0, "current": "", "error": "", "started_at": 0}


def _load_index() -> list[dict[str, Any]]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    WECHAT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=1), encoding="utf-8")


async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"})
    resp.raise_for_status()
    return resp.text


def _parse_article(page_html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(page_html, "html.parser")
    title = (soup.find("h1", id="activity-name") or soup.find("meta", property="og:title"))
    title = (title.get_text(strip=True) if hasattr(title, "get_text") else (title or {}).get("content", "")) if title else ""
    title = re.sub(r"[\\/:*?\"<>|\n\r\t]", " ", html.unescape(title or "未命名")).strip()[:60]
    account_el = soup.find("a", id="js_name") or soup.find("strong", class_="profile_nickname")
    account = account_el.get_text(strip=True) if account_el and hasattr(account_el, "get_text") else ""
    if not account:
        m = re.search(r"var nickname\s*=\s*['\"]([^'\"]+)", page_html) or re.search(
            "d.nick_name = '([^']+)'", page_html
        )
        account = m.group(1) if m else "未知公众号"
    content = soup.find("div", id="js_content")
    date = ""
    m = re.search(r"var ct = ?\"?(\d{10})", page_html)
    if m:
        date = time.strftime("%Y-%m-%d", time.localtime(int(m.group(1))))
    return {"title": title, "account": account, "content": content, "date": date, "url": url, "soup": soup}


async def _download_images(
    client: httpx.AsyncClient, soup_content: BeautifulSoup, img_dir: Path
) -> dict[str, str]:
    """下载正文图片(data-src),返回 原URL→本地文件名 映射。"""
    mapping: dict[str, str] = {}
    img_dir.mkdir(parents=True, exist_ok=True)
    imgs = soup_content.find_all("img")
    for i, img in enumerate(imgs):
        src = img.get("data-src") or img.get("src") or ""
        if not src.startswith("http"):
            continue
        ext = ".gif" if "wx_fmt=gif" in src else ".png" if "wx_fmt=png" in src else ".jpg"
        fname = f"{i:03d}{ext}"
        try:
            r = await client.get(src, headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"})
            r.raise_for_status()
            (img_dir / fname).write_bytes(r.content)
            mapping[src] = fname
            img["src"] = f"images/{fname}"
            if img.get("data-src"):
                del img["data-src"]
        except Exception:  # noqa: BLE001
            continue
        await asyncio.sleep(0.15)
    return mapping


# ---------------------------------------------------------------- 视频下载


def _b64decode(s: str) -> str:
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4)).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def _vid_from_url(url: str) -> str:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        for key in ("vid", "vids", "videncode"):
            if qs.get(key):
                return qs[key][0]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _qs_get(url: str, key: str) -> str:
    try:
        vals = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(key, [])
        return vals[0] if vals else ""
    except Exception:  # noqa: BLE001
        return ""


def _extract_video_embeds(soup_content: Any) -> list[dict[str, Any]]:
    """收集正文里的视频嵌入点(按文档顺序去重),返回 [{el, vid, src}]。"""
    embeds: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(el: Any, vid: str = "", src: str = "") -> None:
        key = vid or src
        if key and key not in seen:
            seen.add(key)
            embeds.append({"el": el, "vid": vid, "src": src})

    for el in soup_content.find_all(["iframe", "mp-common-mpvideo", "video"]):
        name = getattr(el, "name", "")
        if name == "video":
            src = el.get("data-src") or el.get("src") or ""
            if src.startswith("http"):
                _add(el, src=src)
        elif name == "mp-common-mpvideo":
            _add(el, vid=el.get("data-mpvid") or _vid_from_url(el.get("data-src") or ""))
        else:  # iframe:仅认 video_iframe 且能解出 vid 的
            if "video_iframe" not in (el.get("class") or []):
                continue
            src = el.get("data-src") or el.get("src") or ""
            _add(el, vid=_vid_from_url(src) or el.get("data-mpvid") or "")
    return embeds


def _parse_getinfo(text: str) -> dict[str, Any] | None:
    """解析 vv.video.qq.com/getinfo 的 QZOutputJson=…; 响应。"""
    payload = text.strip()
    m = re.search(r"QZOutputJson\s*=\s*(\{.*\})\s*;?\s*$", payload, re.S)
    if m:
        payload = m.group(1)
    try:
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or "vl" not in data or data.get("errcode", 0) != 0:
        return None
    return data


def _pick_wxv_url(text: str) -> str:
    """从 readtemplate video_list 响应里选最高清晰度的 main_url(base64 解码)。"""
    obj: Any = None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except Exception:  # noqa: BLE001
            obj = None
    if obj is None:
        m = re.search(r"video_list\s*=\s*(\{.*\})\s*;?", stripped, re.S)
        if m:
            try:
                obj = json.loads(m.group(1).rstrip().rstrip(";"))
            except Exception:  # noqa: BLE001
                obj = None
    if isinstance(obj, dict):
        lists = obj.get("video_list") if isinstance(obj.get("video_list"), dict) else obj
        best, best_w = "", -1
        for item in lists.values() if isinstance(lists, dict) else []:
            if not isinstance(item, dict):
                continue
            url = _b64decode(item.get("main_url") or "")
            try:
                w = int(item.get("vid_width") or 0)
            except (TypeError, ValueError):
                w = 0
            if url and w >= best_w:
                best, best_w = url, w
        if best:
            return best
    urls = [_b64decode(x) for x in re.findall(r'"main_url"\s*:\s*"([A-Za-z0-9+/=]+)"', text)]
    urls = [u for u in urls if u]
    return urls[-1] if urls else ""


async def _txvideo_play_urls(client: httpx.AsyncClient, vid: str) -> list[str]:
    """腾讯视频(v.qq.com)vid:getinfo 拿 CDN 直链;分段视频返回分段地址列表。"""
    params = {
        "vids": vid,
        "platform": "101001",
        "charge": "0",
        "otype": "json",
        "defsrc": "0",
        "defaultfmt": "mp4",
        "guid": uuid.uuid4().hex,
        "flowid": uuid.uuid4().hex,
        "appver": "3.2.19.333",
        "fhdswitch": "0",
        "defplt": "0",
    }
    r = await client.get("https://vv.video.qq.com/getinfo", params=params, headers={"User-Agent": UA})
    r.raise_for_status()
    info = _parse_getinfo(r.text)
    if not info:
        return []
    try:
        vi = info["vl"]["vi"][0]
        base = ""
        for ui in vi.get("ul", {}).get("ui", []):
            u = (ui.get("url") or "").rstrip("/")
            if u.startswith("http"):
                base = u
                break
        fn, vkey = vi.get("fn", ""), vi.get("fvkey", "")
        if not (base and fn and vkey):
            return []
        cl = vi.get("cl") or {}
        fc = cl.get("fc", 1)
        if fc <= 1 or not fn.endswith(".mp4"):
            return [f"{base}/{fn}?vkey={vkey}"]
        chunks: list[str] = []
        for idx, ci in enumerate(cl.get("ci", []), start=1):
            k = ci.get("key")
            if not k or k == "null":
                k = vkey
            chunk_fn = re.sub(r"\.mp4$", f".{idx}.mp4", fn)
            chunks.append(f"{base}/{chunk_fn}?vkey={k}")
        return chunks if len(chunks) == fc else [f"{base}/{fn}?vkey={vkey}"]
    except (KeyError, IndexError, TypeError):
        return []


async def _wxv_play_url(client: httpx.AsyncClient, vid: str, article_url: str) -> str:
    """公众号原生视频(wxv_):readtemplate 的 video_list 取 main_url。"""
    params: dict[str, str] = {
        "t": "pages/video_list_tmpl",
        "vid": vid,
        "random": f"{random.random():.6f}",
    }
    for key in ("__biz", "mid", "idx", "sn"):
        val = _qs_get(article_url, key)
        if val:
            params[key] = val
    r = await client.get(
        "https://mp.weixin.qq.com/mp/readtemplate",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"},
    )
    r.raise_for_status()
    return _pick_wxv_url(r.text)


async def _save_url_to(client: httpx.AsyncClient, url: str, dest: Path) -> None:
    r = await client.get(url, headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"})
    r.raise_for_status()
    dest.write_bytes(r.content)


def _replace_with_local_video_link(el: Any, href: str) -> None:
    a = el.new_tag("a", href=href)
    a.string = "▶ 本地视频已保存"
    el.replace_with(a)


async def _capture_and_download_wxv_videos(
    article_url: str, vids_in_order: list[str], video_dir: Path
) -> dict[str, Path]:
    """无头浏览器(普通 Chrome UA)打开文章,逐个点播视频并立刻下载签名直链。

    直链时效仅几分钟(dis_t 签名),所以捕获和下载必须同一会话内完成。
    返回 {vid: 本地文件 Path};Playwright/Chrome 不可用或全部失败时返回 {}。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {}
    result: dict[str, Path] = {}
    video_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
        except Exception:  # noqa: BLE001
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception:  # noqa: BLE001
                return {}
        try:
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()
            await page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            count = await page.locator("video").count()
            if count == 0:
                return {}
            async with httpx.AsyncClient(
                timeout=120, follow_redirects=True, trust_env=False
            ) as dl:
                for i in range(count):
                    try:
                        el = page.locator("video").nth(i)
                        await el.scroll_into_view_if_needed(timeout=8000)
                        await page.wait_for_timeout(1200)
                        await page.evaluate(
                            """() => Array.from(document.querySelectorAll('video')).forEach(v => { v.muted = true; })"""
                        )
                        box = await el.bounding_box()
                        if box:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                            )
                        await page.wait_for_timeout(5000)
                        info = await page.evaluate(
                            """(i) => { const v = document.querySelectorAll('video')[i];
                                let e = v.closest('[data-mpvid]');
                                return { vid: e ? e.getAttribute('data-mpvid') : '',
                                         src: v.currentSrc || v.src || '' }; }""",
                            i,
                        )
                        vid = info.get("vid") or ""
                        if not vid and i < len(vids_in_order):
                            vid = vids_in_order[i]
                        src = info.get("src", "")
                        if not (vid and src.startswith("http") and ".mp4" in src):
                            continue
                        fname = f"v{i + 1:03d}_{vid}.mp4"
                        dest = video_dir / fname
                        r = await dl.get(src, headers=_VIDEO_DL_HEADERS)
                        if r.status_code not in (200, 206):
                            raise ValueError(f"CDN 拒绝:{r.status_code}")
                        dest.write_bytes(r.content)
                        result[vid] = dest
                        # 拿到地址即可暂停,释放带宽
                        await page.evaluate(
                            """(i) => { const v = document.querySelectorAll('video')[i]; if (v) v.pause(); }""",
                            i,
                        )
                    except Exception:  # noqa: BLE001
                        continue
        finally:
            await browser.close()
    return result


async def _download_videos(
    client: httpx.AsyncClient,
    soup_content: Any,
    art_dir: Path,
    article_url: str,
    browser_files: dict[str, Path] | None = None,
) -> tuple[int, list[str]]:
    """下载正文内嵌视频到 videos/,原嵌入位置替换为本地链接。返回 (成功数, 失败说明)。

    browser_files:无头浏览器已捕获并下载好的 {vid: 本地文件},直接链接,不再重下。
    其余嵌入退回 httpx 解析路径(腾讯视频 getinfo / 裸 video 直下)。
    """
    embeds = _extract_video_embeds(soup_content)
    if not embeds:
        return 0, []
    video_dir = art_dir / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    browser_files = browser_files or {}
    ok, errors = 0, []
    for i, emb in enumerate(embeds):
        el, vid, direct = emb["el"], emb.get("vid", ""), emb.get("src", "")
        fname = f"v{i + 1:03d}.mp4"
        try:
            if vid and vid in browser_files:
                local = browser_files[vid]
                if local.exists():
                    _replace_with_local_video_link(el, f"videos/{local.name}")
                    ok += 1
                    continue
                raise ValueError("浏览器捕获文件丢失")
            if direct:
                if ".m3u8" in direct:
                    raise ValueError("m3u8 流暂不支持")
                await _save_url_to(client, direct, video_dir / fname)
            elif vid.startswith("wxv_"):
                url = await _wxv_play_url(client, vid, article_url)
                if not url:
                    raise ValueError("video_list 未返回可播地址")
                await _save_url_to(client, url, video_dir / fname)
            elif vid:
                urls = await _txvideo_play_urls(client, vid)
                if not urls:
                    raise ValueError("getinfo 未返回播放地址")
                if len(urls) == 1:
                    await _save_url_to(client, urls[0], video_dir / fname)
                else:  # 分段视频:顺序拼接为一个文件
                    with open(video_dir / fname, "wb") as f:
                        for chunk_url in urls:
                            r = await client.get(chunk_url, headers={"User-Agent": UA})
                            r.raise_for_status()
                            f.write(r.content)
            else:
                continue
            ok += 1
            _replace_with_local_video_link(el, f"videos/{fname}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{(vid or direct)[:40]}: {str(e)[:80]}")
        await asyncio.sleep(0.3)
    return ok, errors


def _to_markdown(title: str, account: str, date: str, url: str, content_html: str) -> str:
    import html2text

    h = html2text.HTML2Text()
    h.ignore_images = False
    h.ignore_links = False
    h.body_width = 0
    body = h.handle(content_html)
    head = f"# {title}\n\n> 公众号:{account} · {date} · [原文]({url})\n\n"
    return head + body


async def download_article(url: str) -> dict[str, Any]:
    """下载单篇文章:md + html + 图片,登记索引。"""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, trust_env=False) as client:
        page = await _fetch(client, url)
        parsed = _parse_article(page, url)
        if parsed["content"] is None:
            raise ValueError("页面里找不到正文(js_content),可能不是标准文章页或已删除")
        slug = f"{parsed['date'] or '无日期'}_{parsed['title']}"
        art_dir = WECHAT_DIR / parsed["account"] / slug
        await _download_images(client, parsed["content"], art_dir / "images")

        # 视频:wxv 原生视频走无头浏览器捕获(签名直链即捕即下),其余嵌入 httpx 兑底
        embeds = _extract_video_embeds(parsed["content"])
        vids_in_order = [e["vid"] for e in embeds if e.get("vid")]
        browser_files: dict[str, Path] = {}
        if vids_in_order:
            browser_files = await _capture_and_download_wxv_videos(
                url, vids_in_order, art_dir / "videos"
            )
        videos, video_errors = await _download_videos(
            client, parsed["content"], art_dir, url, browser_files
        )

        content_html = str(parsed["content"])
        md = _to_markdown(parsed["title"], parsed["account"], parsed["date"], url, content_html)
        (art_dir / "article.md").write_text(md, encoding="utf-8")
        html_doc = (
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{parsed['title']}</title>{content_html}"
        )
        (art_dir / "article.html").write_text(html_doc, encoding="utf-8")

        entry = {
            "id": uuid.uuid4().hex[:10],
            "ts": time.time(),
            "title": parsed["title"],
            "account": parsed["account"],
            "date": parsed["date"],
            "url": url,
            "dir": str(art_dir.relative_to(PROJECT_ROOT)),
            "images": len(list((art_dir / "images").glob("*"))) if (art_dir / "images").exists() else 0,
            "videos": videos,
            **({"video_errors": video_errors[:5]} if video_errors else {}),
        }
        items = _load_index()
        if not any(i["url"] == url for i in items):
            items.append(entry)
            _save_index(items)
        return entry


def parse_collection(page_html: str) -> list[dict[str, str]]:
    """解析合集(appmsgalbum)页,返回 [{title,url}]。合集公开可分页浏览。"""
    items: list[dict[str, str]] = []
    for m in re.finditer(
        r'<a[^>]+href="([^"]*mp\.weixin\.qq\.com/s[^"]*)"[^>]*>\s*<[^>]*class="album__item[^"]*"[^>]*>.*?<p class="album__item-title-wrp"[^>]*>\s*<span[^>]*>([^<]+)</span>',
        page_html,
        re.S,
    ):
        url_ = html.unescape(m.group(1)).replace("&amp;", "&")
        title = html.unescape(m.group(2)).strip()
        if url_ and title:
            items.append({"title": title, "url": url_})
    if not items:
        # 兜底:任何指向 /s 的链接
        for m in re.finditer(r'href="([^"]*mp\.weixin\.qq\.com/s\?[^"]+)"', page_html):
            url_ = html.unescape(m.group(1)).replace("&amp;", "&")
            if not any(i["url"] == url_ for i in items):
                items.append({"title": "", "url": url_})
    return items


async def collect_urls_from_pages(start_url: str, max_pages: int = 10) -> list[dict[str, str]]:
    """合集翻页收集全部文章链接。"""
    all_items: list[dict[str, str]] = []
    url = start_url
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, trust_env=False) as client:
        for _ in range(max_pages):
            if not url:
                break
            page = await _fetch(client, url)
            items = parse_collection(page)
            fresh = [i for i in items if not any(a["url"] == i["url"] for a in all_items)]
            all_items.extend(fresh)
            m = re.search(r'href="([^"]*appmsgalbum[^"]*continue[^"]*)"', page) or re.search(
                r"var continue_flag = '1'", page
            )
            nxt = re.search(r'href="([^"]*appmsgalbum[^"]*?begin_item_id=[^"]*)"', page)
            if nxt:
                url = html.unescape(nxt.group(1)).replace("&amp;", "&")
            else:
                break
            await asyncio.sleep(1.0)
    return all_items


async def run_collection_task(start_url: str, max_pages: int = 10) -> dict[str, Any]:
    """后台任务:合集 → 逐篇下载。"""
    if _task_state["running"]:
        return {"ok": False, "error": "已有合集任务在跑"}
    _task_state.update(
        running=True, kind="collection", total=0, done=0, current="", error="", started_at=time.time()
    )
    try:
        urls = await collect_urls_from_pages(start_url, max_pages)
        _task_state["total"] = len(urls)
        for it in urls:
            _task_state["current"] = it["title"] or it["url"][:60]
            try:
                await download_article(it["url"])
                _task_state["done"] += 1
            except Exception as e:  # noqa: BLE001
                _task_state["error"] = f"{(it.get('title') or '')[:30]}: {str(e)[:100]}"
            await asyncio.sleep(2.0)
        return {"ok": True, "total": _task_state["total"], "done": _task_state["done"]}
    finally:
        _task_state["running"] = False


def task_status() -> dict[str, Any]:
    return dict(_task_state)
