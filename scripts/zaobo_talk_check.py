# -*- coding: utf-8 -*-
"""校验《评论区话术库》里的每一条话术：硬禁令、长度、发布风险、档案禁区。

设计取舍：**直接读 markdown 文件**，不在脚本里另存一份话术。
话术库是真源，脚本是尺子；两边各存一份必然会漂移（回复只是一段话，
肉眼改一句很常见，改完忘了同步脚本就是假通过）。

四个检查项，任何一项没过都会打印出来并让退出码为 1：

1. ``check_reply_style`` 硬禁令（破折号/提示性冒号/翻案腔/黑话/结尾反问…）
2. 长度 ≤ ``MAX_CHARS``（默认 260，**只是糊弄不过去的兜底，不是发布标准** ——
   官方号回复本来就比普通评论长，真实评论 p99 是 164 字，260 是「明显失控」的线）
3. ``assess_content`` 无 high 风险项（绝对化用语/导流/医疗金融越界）
4. 档案 ``forbidden`` 里的效果承诺词（弱承诺句式，见 README 说明）

用法：
    uv run python scripts/zaobo_talk_check.py
    uv run python scripts/zaobo_talk_check.py --text "随手写的一条"
    uv run python scripts/zaobo_talk_check.py --max-chars 300
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.content_quality import QUALITY_VERSION, assess_content  # noqa: E402
from api.services.outreach.reply_style import check_reply_style  # noqa: E402

DOC = ROOT / "docs/早播/评论区话术库_2026-11-12.md"
PROFILES = ROOT / "data/project_profiles.json"

MAX_CHARS = 260
PROFILE_ID = "早播"

# 条目形如：
#   **13. 上车到下车那段路**　触发：「…」　｜二档
#   > 我那段路就是点一下然后手不用再碰…
_ITEM_RE = re.compile(
    r"^\*\*(\d+)\.\s*(?P<scene>[^*]+)\*\*[^\n]*\n\n?>\s*(?P<text>[^\n]+)",
    re.MULTILINE,
)

# 弱承诺：档案 forbidden 禁的是「效果」，但代码里的 risk_promise 只认
# 「保证/一定/必然」这类强词 + 效果词同句。样本里那两条用的「会有」「会感觉」
# 正是从这个缝里过去的（194/213 字、各 78 分、0 命中）。
# 这里补一道窄的：**弱承诺句式 + 效果词**才算命中，避免误伤「会有结尾」这类描述。
_WEAK_PROMISE_RE = re.compile(
    r"(会有|会感觉|就会|能让你|让你|变得|慢慢|几个月|一阵子|坚持)[^。！？\n]{0,16}"
    r"(提升|变好|平静|专注|记住|摆脱|戒掉|治愈|改善|恢复|减轻|上瘾|焦虑)"
)

# 明确不能出现在回复里的效果承诺（档案 forbidden 第 2/5/8/9/12 条的语言形态）
_FORBIDDEN_PHRASES = (
    "认知提升",
    "视野提升",
    "明显提升",
    "提升认知",
    "变得专业",
    "显得专业",
    "保证记住",
    "改善睡眠",
    "改善注意力",
    "消除焦虑",
    "解决孤独",
    "戒掉手机",
    "治好",
)


def _load_forbidden() -> list[str]:
    if not PROFILES.exists():
        return []
    data = json.loads(PROFILES.read_text(encoding="utf-8"))
    for profile in data.get("profiles", []):
        if profile.get("profile_id") == PROFILE_ID:
            return list(profile.get("forbidden") or [])
    return []


def _items() -> list[dict]:
    """从 markdown 里抽出全部话术条目。"""
    if not DOC.exists():
        return []
    return [
        {
            "no": m.group(1),
            "scene": m.group("scene").strip(),
            "text": m.group("text").strip(),
        }
        for m in _ITEM_RE.finditer(DOC.read_text(encoding="utf-8"))
    ]


def check(text: str, *, max_chars: int = MAX_CHARS) -> list[str]:
    """返回这条话术的问题列表，空列表 = 通过。"""
    problems: list[str] = []

    for warning in check_reply_style(text):
        problems.append(f"风格：{warning}")

    if len(text) > max_chars:
        problems.append(f"长度：{len(text)} 字，超过 {max_chars} 字上限")

    quality = assess_content(body=text, platform="xhs")
    for issue in quality.issues:
        if issue.severity == "high":
            problems.append(f"风险：{issue.message}")

    hit = _WEAK_PROMISE_RE.search(text)
    if hit:
        problems.append(f"弱承诺：{hit.group(0)!r}（档案 forbidden 禁效果承诺）")
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in text:
            problems.append(f"禁区词：{phrase!r}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验评论区话术库")
    parser.add_argument("--text", help="只校验这一条，不读话术库")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    args = parser.parse_args(argv)

    if args.text:
        problems = check(args.text, max_chars=args.max_chars)
        print(f"[{'FAIL' if problems else 'OK'}] {len(args.text)} 字")
        for p in problems:
            print(f"  - {p}")
        return 1 if problems else 0

    items = _items()
    if not items:
        print(f"未在 {DOC} 里找到话术条目（检查条目标题格式是否被改动）")
        return 1

    forbidden = _load_forbidden()
    failures = 0
    for item in items:
        problems = check(item["text"], max_chars=args.max_chars)
        if problems:
            failures += 1
            print(f"[FAIL] #{item['no']} {item['scene']}（{len(item['text'])} 字）")
            for p in problems:
                print(f"       - {p}")

    print(
        f"\n共 {len(items)} 条，通过 {len(items) - failures} 条，"
        f"失败 {failures} 条；档案「{PROFILE_ID}」禁区 {len(forbidden)} 条已加载"
        f"（{QUALITY_VERSION}）"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
