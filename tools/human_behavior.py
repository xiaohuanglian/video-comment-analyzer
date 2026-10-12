# -*- coding: utf-8 -*-
"""拟人操作原语：平滑滚动、鼠标轨迹、重尾停留时间。

集中放在一处，供小红书受控回复与浏览式采集共用。要点：

- 滚动：滚轮事件是一小步一小步的（真人一次滚 1-3 格），不是 scrollBy 瞬移
- 鼠标：点击前有移动轨迹（多段插值 + 目标点随机偏移），不瞬移到元素中心
- 停留时间：重尾分布（对数正态），大多数短暂划过、偶尔看很久，不是均匀分布
"""

from __future__ import annotations

import math
import random
from typing import Optional

try:
    from playwright.async_api import Locator, Page
except Exception:  # pragma: no cover
    Page = None  # type: ignore[assignment]
    Locator = None  # type: ignore[assignment]


async def human_pause(lo: float = 0.4, hi: float = 1.5) -> None:
    """短停顿（操作之间），均匀分布即可。"""
    import asyncio

    await asyncio.sleep(random.uniform(lo, hi))


async def dwell_seconds(quick_p: float = 0.55, lo: float = 1.0, mid: float = 4.0, hi: float = 25.0) -> float:
    """重尾停留时长（看一篇内容/一个页面）。

    以概率 quick_p 快速划过（lo~mid），否则认真看（mid~hi 的对数正态）。
    真人浏览大多几秒划过，偶尔停留很久，重尾比均匀分布更真实。
    """
    if random.random() < quick_p:
        return random.uniform(lo, mid)
    # 对数正态尾部：偶发长停留
    return min(hi, mid * math.exp(random.gauss(0.7, 0.9)))


async def smooth_scroll(
    page: "Page",
    distance: int,
    *,
    step_range: tuple[int, int] = (90, 260),
    step_pause: tuple[float, float] = (0.04, 0.16),
) -> None:
    """拟人滚动：分多次小步滚轮事件推进 distance 像素。

    偶尔（约 15%）回滚一小段再继续，真人常这么干。
    """
    import asyncio

    remaining = distance
    while remaining > 0:
        step = min(random.randint(*step_range), remaining)
        await page.mouse.wheel(0, step)
        remaining -= step
        await asyncio.sleep(random.uniform(*step_pause))
        if remaining > 400 and random.random() < 0.15:
            back = random.randint(60, 180)
            await page.mouse.wheel(0, -back)
            remaining += back
            await asyncio.sleep(random.uniform(*step_pause))


async def scroll_container_smooth(
    page: "Page",
    selector: str,
    distance: int,
) -> None:
    """拟人滚动指定容器（如 .note-scroller），同样分小步推进。"""
    import asyncio

    remaining = distance
    while remaining > 0:
        step = min(random.randint(90, 220), remaining)
        await page.evaluate(
            "([sel, delta]) => { const el = document.querySelector(sel); if (el) el.scrollBy({top: delta, behavior: 'instant'}); }",
            [selector, step],
        )
        remaining -= step
        await asyncio.sleep(random.uniform(0.05, 0.18))


async def move_mouse_to(
    page: "Page",
    x: float,
    y: float,
    *,
    steps: Optional[int] = None,
) -> None:
    """带轨迹的鼠标移动：从当前位置分 6-14 段插值移动到目标附近。

    目标点加随机偏移（±3px），避免每次都点在精确的元素中心。
    """
    import asyncio

    steps = steps or random.randint(6, 14)
    jitter_x = random.uniform(-3, 3)
    jitter_y = random.uniform(-3, 3)
    tx, ty = x + jitter_x, y + jitter_y
    # 取当前鼠标位置不可靠，从目标附近的随机起点附近出发即可近似轨迹
    sx = tx + random.uniform(-120, 120)
    sy = ty + random.uniform(-80, 80)
    for i in range(1, steps + 1):
        t = i / steps
        # 轻微弧线：中点法向偏移
        arc = math.sin(t * math.pi) * random.uniform(-18, 18)
        px = sx + (tx - sx) * t + arc
        py = sy + (ty - sy) * t
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.008, 0.03))
    await page.mouse.move(tx, ty)


async def human_click(page: "Page", locator: "Locator", *, timeout: int = 5000) -> None:
    """带轨迹的拟人点击：取元素包围盒 → 鼠标移过去 → 点击。"""
    box = await locator.bounding_box(timeout=timeout)
    if box is None:
        # 拿不到包围盒时退回原生 click
        await locator.click(timeout=timeout)
        return
    x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
    y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
    await move_mouse_to(page, x, y)
    await human_pause(0.05, 0.25)
    await page.mouse.down()
    await human_pause(0.03, 0.12)
    await page.mouse.up()
