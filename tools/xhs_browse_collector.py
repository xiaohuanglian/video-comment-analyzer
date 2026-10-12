# -*- coding: utf-8 -*-
"""小红书浏览式采集：用真实浏览器刷笔记，顺手从 DOM 提取评论。

思路：不做任何 API 请求，风控看到的就是一个用户在搜索关键词、
逐篇打开笔记、滚动看评论。评论数据在页面 DOM 里天然存在，
笔记链接自带的 xsec_token 一并保存，后续受控回复直接复用。

输出 CSV 与爬虫存储层同构（comment_id/note_id/content/nickname/
user_id/xsec_token/comment_url/...），可直接进入洞察 ingestion。
"""

from __future__ import annotations

import asyncio
import csv
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from tools import utils

try:
    from playwright.async_api import Browser, Page
except Exception:  # pragma: no cover
    Page = None  # type: ignore[assignment]
    Browser = None  # type: ignore[assignment]

from api.services.insight.xhs_reply_sender import ReplySendError, _connect_browser, _pick_context

_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_explore_feed"

# DOM 提取脚本：笔记元信息 + 全部已加载评论（父/子关系一并解析）
_EXTRACT_JS = """() => {
  const res = {};
  res.noteTitle = (document.querySelector('#detail-title') || {}).innerText || '';
  res.creatorName = (document.querySelector('.author .username') || {}).innerText || '';
  const creatorHref = (document.querySelector('.author a') || {}).getAttribute?.('href') || '';
  res.creatorId = (creatorHref.match(/profile\\/([a-f0-9]+)/) || [])[1] || '';
  const comments = [];
  for (const item of document.querySelectorAll('.comment-item')) {
    const id = (item.id || '').replace('comment-', '');
    if (!id) continue;
    const parentEl = item.closest('.parent-comment');
    const parentId = (parentEl && parentEl.id || '').replace('comment-', '');
    comments.push({
      id: id,
      user: (item.querySelector('.author .name') || {}).innerText || '',
      userId: (item.querySelector('.author a') || {}).getAttribute?.('data-user-id') || '',
      content: (item.querySelector('.content .note-text') || {}).innerText || '',
      date: (item.querySelector('.date') || {}).innerText || '',
      like: (item.querySelector('.like .count') || {}).innerText || '0',
      isSub: item.className.includes('comment-item-sub'),
      parentId: (!item.className.includes('comment-item-sub') || !parentId) ? '' : parentId,
    });
  }
  res.comments = comments;
  return res;
}"""


@dataclass
class BrowseNoteResult:
    note_id: str
    xsec_token: str
    url: str
    title: str = ""
    creator_name: str = ""
    creator_id: str = ""
    comments: List[dict] = field(default_factory=list)


async def _human_pause(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


def _parse_note_url(url: str) -> tuple[str, str]:
    """从链接提取 (note_id, xsec_token)。

    支持两种笔记链接：``/explore/<id>`` 与搜索结果的 ``/search_result/<id>``。
    """
    note_id = ""
    token = ""
    m = re.search(r"/(?:explore|search_result)/([a-f0-9]+)", url or "", re.IGNORECASE)
    if m:
        note_id = m.group(1)
    m = re.search(r"[?&]xsec_token=([^&#]+)", url or "")
    if m:
        token = m.group(1)
    return note_id, token


async def search_note_links(page: "Page", keyword: str, max_notes: int) -> List[dict]:
    """搜索关键词并收集笔记链接（含 xsec_token）。"""
    url = _SEARCH_URL.format(keyword=keyword)
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await _human_pause(2.0, 4.0)
    # 滚两轮 feed 让链接加载出来
    for _ in range(2):
        await page.mouse.wheel(0, random.randint(800, 1600))
        await _human_pause(1.0, 2.5)
    hrefs = await page.evaluate(
        """(maxNotes) => {
          // 搜索结果的笔记链接是 /search_result/<id>?xsec_token=...（带令牌），
          // 无令牌的 /explore/<id> 直链会被风控 404，只作兑底。
          const byNote = new Map();
          for (const a of document.querySelectorAll('a[href*="note_id="], a[href*="/explore/"], a[href*="/search_result/"]')) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/\\/(?:explore|search_result)\\/([a-f0-9]+)/);
            if (!m) continue;
            const noteId = m[1];
            const t = (href.match(/[?&]xsec_token=([^&#]+)/) || [])[1] || '';
            const prev = byNote.get(noteId) || {note_id: noteId, xsec_token: '', url: ''};
            if (t && !prev.xsec_token) {
              const path = '/explore/' + noteId + '?xsec_token=' + t + '&xsec_source=pc_search';
              byNote.set(noteId, {note_id: noteId, xsec_token: t, url: 'https://www.xiaohongshu.com' + path});
            } else if (!byNote.has(noteId)) {
              byNote.set(noteId, prev);
            }
          }
          return Array.from(byNote.values()).filter(n => n.xsec_token).slice(0, maxNotes);
        }""",
        max_notes,
    )
    return hrefs or []


async def harvest_note(page: "Page", url: str, *, max_scroll_rounds: int = 10) -> BrowseNoteResult:
    """打开一篇笔记，滚动加载评论并从 DOM 提取。"""
    note_id, token = _parse_note_url(url)
    result = BrowseNoteResult(note_id=note_id, xsec_token=token, url=url)
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await _human_pause(2.0, 4.0)
    try:
        await page.wait_for_selector(".comments-container", timeout=15000)
    except Exception as exc:
        raise ReplySendError(f"笔记 {note_id} 评论区未加载（可能需登录或已删除）：{exc}") from exc

    # 滚动 .note-scroller 逐步加载评论，直到数量不再增长
    prev = -1
    for _ in range(max_scroll_rounds):
        data = await page.evaluate(_EXTRACT_JS)
        count = len(data.get("comments") or [])
        if count <= prev and _ > 0:
            break
        prev = count
        await page.evaluate("document.querySelector('.note-scroller')?.scrollBy(0, 1200)")
        await _human_pause(0.8, 2.0)
    data = await page.evaluate(_EXTRACT_JS)
    result.title = (data.get("noteTitle") or "").strip()
    result.creator_name = (data.get("creatorName") or "").strip()
    result.creator_id = data.get("creatorId") or ""
    result.comments = data.get("comments") or []
    return result


_COMMENT_COLUMNS = [
    "comment_id",
    "note_id",
    "content",
    "nickname",
    "user_id",
    "parent_comment_id",
    "like_count",
    "sub_comment_count",
    "ip_location",
    "create_time",
    "xsec_token",
    "comment_url",
    "video_title",
    "creator_name",
    "platform",
]


def _comment_row(note: BrowseNoteResult, c: dict) -> dict:
    comment_url = (
        f"https://www.xiaohongshu.com/explore/{note.note_id}"
        f"?xsec_token={note.xsec_token}&xsec_source=pc_search#comment-{c.get('id')}"
        if note.xsec_token
        else ""
    )
    return {
        "comment_id": c.get("id") or "",
        "note_id": note.note_id,
        "content": c.get("content") or "",
        "nickname": c.get("user") or "",
        "user_id": c.get("userId") or "",
        "parent_comment_id": c.get("parentId") or "",
        "like_count": c.get("like") or "0",
        "sub_comment_count": "",
        "ip_location": "",
        "create_time": c.get("date") or "",
        "xsec_token": note.xsec_token,
        "comment_url": comment_url,
        "video_title": note.title,
        "creator_name": note.creator_name,
        "platform": "xhs",
    }


def write_results(results: List[BrowseNoteResult], out_dir: Path) -> Path:
    """写 comments.csv（与爬虫存储层同构，可直接 ingestion）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "comments.csv"
    rows = [_comment_row(note, c) for note in results for c in note.comments]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COMMENT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


async def run_browse_collection(
    *,
    keywords: Optional[List[str]] = None,
    note_urls: Optional[List[str]] = None,
    max_notes_per_keyword: int = 5,
    max_comments_scroll_rounds: int = 10,
    note_pause_seconds: tuple[float, float] = (12.0, 35.0),
    out_dir: Optional[Path] = None,
    browser: Optional["Browser"] = None,
) -> tuple[Path, List[BrowseNoteResult]]:
    """浏览式采集入口：搜索/指定链接 → 逐篇浏览提取 → 落 CSV。

    ``note_pause_seconds`` 是两篇笔记之间的停留区间（秒），刻意比 API
    采集慢：这是给风控看的浏览行为，不是抓取行为。
    """
    keywords = keywords or []
    note_urls = note_urls or []
    if not keywords and not note_urls:
        raise ValueError("需要提供 keywords 或 note_urls 至少一项")

    owned = browser is None
    browser = browser or await _connect_browser()
    try:
        ctx = await _pick_context(browser)
        page = await ctx.new_page()
        targets: List[dict] = []
        try:
            for kw in keywords:
                utils.logger.info(f"[xhs_browse] 搜索关键词：{kw}")
                links = await search_note_links(page, kw, max_notes_per_keyword)
                utils.logger.info(f"[xhs_browse] 「{kw}」找到 {len(links)} 篇笔记")
                targets.extend(links)
            for url in note_urls:
                note_id, token = _parse_note_url(url)
                if note_id:
                    targets.append({"note_id": note_id, "xsec_token": token, "url": url})
            # 去重
            seen = set()
            unique = []
            for t in targets:
                if t["note_id"] not in seen:
                    seen.add(t["note_id"])
                    unique.append(t)

            results: List[BrowseNoteResult] = []
            for i, t in enumerate(unique):
                utils.logger.info(f"[xhs_browse] ({i + 1}/{len(unique)}) 浏览笔记 {t['note_id']}")
                try:
                    note = await harvest_note(
                        page, t["url"], max_scroll_rounds=max_comments_scroll_rounds
                    )
                    results.append(note)
                    utils.logger.info(
                        f"[xhs_browse]   标题《{note.title[:20]}》评论 {len(note.comments)} 条"
                    )
                except ReplySendError as exc:
                    utils.logger.warning(f"[xhs_browse]   跳过：{exc}")
                if i < len(unique) - 1:
                    await _human_pause(*note_pause_seconds)
        finally:
            try:
                await page.close()
            except Exception:
                pass

        out_dir = out_dir or Path("data") / "xhs_browse" / datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = write_results(results, out_dir)
        utils.logger.info(f"[xhs_browse] 完成：{len(results)} 篇笔记 → {csv_path}")
        return csv_path, results
    finally:
        if owned:
            try:
                await browser.close()
            except Exception:
                pass
