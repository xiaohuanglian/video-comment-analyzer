# -*- coding: utf-8 -*-
"""画像校准实验（2026-10-13 用户提出：画像规则未验证是隐藏大问题）。

用法：
  # 1. 抽样：生成标注文件
  uv run python scripts/persona_calibration.py sample --n 30
  # 2. 人工：打开 JSON，把每条 true_persona 从 null 改成你的判断
  #    （合法值见 PERSONA_TAXONOMY，打不开就填 "其他" 并写 note）
  # 3. 评分：
  uv run python scripts/persona_calibration.py score

校准逻辑：抽样带模型画像标签 → 人工判真实身份 → 对比准确率。
人工判断才是金标准；模型错了改 PERSONA_DEFS/先验规则再重跑。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api.services.growth.audience import (  # noqa: E402
    DEFAULT_DATA_DIRS,
    PERSONA_DEFS,
    analyze_comments,
    infer_persona,
    load_bili_comments,
)

PERSONA_TAXONOMY = [name for name, _, _ in PERSONA_DEFS] + ["其他"]
OUT_DIR = PROJECT_ROOT / "data" / "audience"


def cmd_sample(n: int, seed: int = 13) -> None:
    rows, video_map, dataset_ref = load_bili_comments()
    if not rows:
        print("没有采集数据，先跑一轮采集")
        return
    report = analyze_comments(rows, video_map)
    clusters = [c for c in report["clusters"] if c["demand_count"] >= 5]
    if not clusters:
        print("没有 ≥5 条需求的聚类，样本不足")
        return
    rng = random.Random(seed)
    samples = []
    emoji_pat = re.compile(r"\[[^\]]{1,12}\]")  # B 站表情代码如 [星星眼]
    pool = []
    for row in rows:
        text = str(row.get("content") or "").strip()
        if not 8 <= len(text) <= 120:
            continue
        if len(emoji_pat.sub("", text).strip()) < 6:  # 剩不下实内容的纯表情，无法人工判身份
            continue
        pool.append((row, text))
    rng.shuffle(pool)
    picked: list[dict] = []
    for row, text in pool:
        if len(picked) >= n:
            break
        vid = str(row.get("video_id") or "")
        video = video_map.get(vid, {})
        ctx = f"{video.get('title', '')} {video.get('source_keyword', '')}"
        persona, _ = infer_persona(text, ctx)
        picked.append(
            {
                "idx": len(picked) + 1,
                "comment_id": str(row.get("comment_id") or ""),
                "text": text,
                "video_title": str(video.get("title") or "")[:60],
                "model_persona": persona,
                "true_persona": None,  # ← 人工填这里
                "note": "",
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"calibration_{datetime.now().strftime('%Y%m%d')}.json"
    out.write_text(
        json.dumps(
            {
                "_说明": "把每条 true_persona 从 null 改为你的判断；合法值: "
                + " / ".join(PERSONA_TAXONOMY)
                + "。填完跑 score。",
                "samples": picked,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"抽样 {len(picked)} 条 → {out}")
    print(f"人工标注后运行: uv run python scripts/persona_calibration.py score --file {out.name}")


def cmd_score(filename: str | None = None) -> None:
    if filename is None:
        files = sorted(OUT_DIR.glob("calibration_*.json"))
        if not files:
            print("找不到标注文件，先跑 sample")
            return
        filename = files[-1].name
    path = OUT_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = [s for s in data["samples"] if s.get("true_persona")]
    if not samples:
        print(f"{path} 里还没有任何 true_persona 标注")
        return
    correct = sum(1 for s in samples if s["true_persona"] == s["model_persona"])
    print(f"\n=== 画像校准结果（{len(samples)} 条已标注 / 共 {len(data['samples'])} 条）===")
    print(f"总体准确率: {correct}/{len(samples)} = {correct / len(samples):.0%}\n")
    print("模型画像 → 人工判断 分布（看哪类错得离谱）:")
    conf = defaultdict(Counter)
    for s in samples:
        conf[s["model_persona"]][s["true_persona"]] += 1
    for model_p, dist in sorted(conf.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(dist.values())
        hit = dist.get(model_p, 0)
        detail = ", ".join(f"{k}×{v}" for k, v in dist.most_common())
        print(f"  模型判[{model_p}] {total}条 · 命中{hit} ({hit / total:.0%}) → 人工实际: {detail}")
    print("\n标注原文抽查（错样本优先看）:")
    wrong = [s for s in samples if s["true_persona"] != s["model_persona"]]
    for s in (wrong or samples)[:8]:
        print(f"  [{s['model_persona']}→{s['true_persona']}] {s['text'][:60]}")
    if correct / len(samples) < 0.6:
        print("\n⚠️ 准确率 <60%：persona 规则/视频先验需要修——把典型错案发我，我来调规则")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("sample")
    p1.add_argument("--n", type=int, default=30)
    p1.add_argument("--seed", type=int, default=13)
    p2 = sub.add_parser("score")
    p2.add_argument("--file", default=None)
    args = ap.parse_args()
    if args.cmd == "sample":
        cmd_sample(args.n, args.seed)
    else:
        cmd_score(args.file)
