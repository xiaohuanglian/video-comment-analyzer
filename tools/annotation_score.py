"""统计人工标注结果：动作标签的人机一致率。

用法：
    uv run python tools/annotation_score.py docs/标注_论证链人机一致率_2026-11-03.csv

读人工填好的两列（人工判定 / 人工应标动作），输出：
- 总体人工一致率（判「对」的比例）
- 每个动作的一致率（低于 0.6 的动作就是分类不稳的地方）
- 混淆最多的动作对（系统标 A、人工认为更像 B）
- 与系统自评一致率（check_consistency 的 overall）的差距

只看「够不够格」，不看上下文——和系统判定条件保持一致。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

RIGHT = {"对", "是", "1", "true", "True", "y", "Y", "✓", "ok", "OK"}
WRONG = {"错", "否", "0", "false", "False", "n", "N", "×", "x"}


def _norm(value: str) -> str:
    v = (value or "").strip()
    if v in RIGHT:
        return "right"
    if v in WRONG:
        return "wrong"
    return ""


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f)]


def score(rows: List[Dict[str, str]]) -> Dict[str, object]:
    graded = []
    skipped = 0
    for row in rows:
        verdict = _norm(row.get("人工判定") or "")
        if not verdict:
            skipped += 1
            continue
        graded.append((row, verdict))

    if not graded:
        return {
            "graded": 0,
            "skipped": skipped,
            "human_consistency": None,
            "per_move": [],
            "confusions": [],
        }

    right = sum(1 for _, v in graded if v == "right")
    per_move: Dict[str, List[int]] = {}
    confusions: Counter[Tuple[str, str]] = Counter()
    for row, verdict in graded:
        move = (row.get("系统判定动作") or "").strip()
        stat = per_move.setdefault(move, [0, 0])
        stat[1] += 1
        if verdict == "right":
            stat[0] += 1
        else:
            claimed = (row.get("人工应标动作") or "").strip()
            if claimed and claimed != move:
                confusions[(move, claimed)] += 1

    per_move_out = sorted(
        (
            {
                "move": move,
                "label": (next((r.get("动作名") for r, _ in graded if r.get("系统判定动作") == move), "") or ""),
                "right": hit,
                "total": total,
                "ratio": round(hit / total, 2),
            }
            for move, (hit, total) in per_move.items()
        ),
        key=lambda x: (x["ratio"], -x["total"]),
    )

    return {
        "graded": len(graded),
        "skipped": skipped,
        "human_consistency": round(right / len(graded), 2),
        "per_move": per_move_out,
        "confusions": [
            {"system": a, "human": b, "count": c} for (a, b), c in confusions.most_common(10)
        ],
    }


def render(result: Dict[str, object], *, system_overall: float | None = None) -> str:
    lines: List[str] = []
    if not result["graded"]:
        return "还没有填写任何「人工判定」。填 `对` 或 `错` 后再跑一次。"

    lines.append(f"已判定 {result['graded']} 条；未填 {result['skipped']} 条")
    lines.append(f"人工一致率（判「对」的比例）：{result['human_consistency']}")
    if system_overall is not None:
        gap = round(float(result["human_consistency"]) - system_overall, 2)
        lines.append(f"系统自评一致率：{system_overall}　差距：{gap:+}")
        lines.append(
            "→ 人工明显低于系统自评，说明系统对自己太宽松；明显高于，说明 rubric 过严。"
        )

    lines.append("")
    lines.append("按动作拆开（ratio 从低到高，低于 0.6 的就是不稳之处）：")
    for item in result["per_move"]:
        lines.append(f"  {item['move']:<22}{item['label']:<18}{item['right']}/{item['total']} = {item['ratio']}")

    if result["confusions"]:
        lines.append("")
        lines.append("混淆最多的动作对（系统标 → 人工认为更像）：")
        for c in result["confusions"]:
            lines.append(f"  {c['system']} → {c['human']}　{c['count']} 次")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统计论证链动作标签的人工一致率")
    parser.add_argument("csv", type=Path, help="人工标注表路径")
    parser.add_argument("--system-overall", type=float, default=None, help="系统自评一致率，用于对比")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(f"找不到文件：{args.csv}", file=sys.stderr)
        return 2
    result = score(read_rows(args.csv))
    print(render(result, system_overall=args.system_overall))
    return 0 if result["graded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
