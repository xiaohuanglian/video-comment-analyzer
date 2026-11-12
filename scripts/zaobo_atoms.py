# -*- coding: utf-8 -*-
"""早播：把「需求画像表」与「小红书笔记语料」拆成原子，并算可复算的对比数字。

只做三件事，全部可复跑（换一批采集结果会自己更新）：

1. 需求原子：把 xlsx 的 16 条需求拆成 人/场景/卡点/替代/期望/边界 六元组，
   并按关键词推断它服务哪一类人（segment）。
2. 表达原子：从笔记标题里抽结构特征（清单体/人称/疑问/时长限定…），
   用**中位点赞**做对比，避免被个别爆款拉偏均值。
3. 重组缺口：人 × 需求类型的交叉表，标出表里已有与尚未覆盖的格子。

数字只由代码算；报告里引用的每个数都能在这里复现。
"""

from __future__ import annotations

import json
import re
import statistics as st
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "docs" / "早播" / "早播小红书用户需求画像.xlsx"
NOTES = ROOT / "data" / "xhs_search" / "20261111_200159" / "notes.json"
OUT = ROOT / "data" / "早播" / "atoms.json"

#: 人群：早播的受众不是一个人，是几种被不同场景逼出同一动作的人。
SEGMENTS: dict[str, dict[str, Any]] = {
    "通勤族": {
        "label": "通勤/驾车的人",
        "cue": ["通勤", "驾车", "开车", "地铁", "公交", "路上", "手眼", "屏幕"],
        "say": "手在方向盘上，眼睛不能看屏幕",
    },
    "信息型打工人": {
        "label": "工作涉及 AI/科技/商业的人",
        "cue": ["AI", "科技", "商业", "行业", "工作", "同事", "术语", "更新"],
        "say": "同事聊的东西我接不上话",
    },
    "减刷中的人": {
        "label": "已经在减少刷手机的人",
        "cue": ["减少", "戒", "少刷", "碎片", "收藏", "换平台", "打开"],
        "say": "我已经在少刷了，但怕漏掉",
    },
    "低精力的人": {
        "label": "下班/睡前没力气的人",
        "cue": ["疲倦", "压力", "睡前", "下班", "低", "精力", "休息", "累"],
        "say": "我不想再学东西，只想听点",
    },
    "独处的人": {
        "label": "独处、需要陪伴或打发时间的人",
        "cue": ["独处", "陪伴", "聊天", "无聊", "消遣", "空闲", "散步"],
        "say": "一个人待着，想有点动静",
    },
}

#: 标题结构特征。key → (中文名, 判定函数)
FEATURES: dict[str, tuple[str, Any]] = {
    "list": ("清单体", lambda t: bool(re.search(r"(清单|盘点|合集|\d+\s*个|\d+\s*件|TOP|top|推荐|从.+到)", t))),
    "person": ("人称", lambda t: bool(re.search(r"(我|你|我们)", t))),
    "duration": ("时长/数量限定", lambda t: bool(re.search(r"[（(]?\d+\s*(分钟|min|天|小时|步|期)", t, re.I))),
    "counterintuitive": ("反常识转折", lambda t: bool(re.search(r"(其实|不是|才|真相|误解|原来|反而|反而)", t))),
    "loss": ("损失/戒断词", lambda t: bool(re.search(r"(毁|戒|摆脱|拯救|夺回|控制|停不下来|腐蚀|焦虑|陷阱|毁掉)", t))),
    "assertive": ("强断言词", lambda t: bool(re.search(r"(必|一定|绝对|彻底|封神|神器|最|超|狠狠|太太太)", t))),
    "number": ("含数字", lambda t: bool(re.search(r"\d", t))),
    "exclaim": ("感叹号", lambda t: bool(re.search(r"[!！]", t))),
    "question": ("疑问句", lambda t: bool(re.search(r"[？?]|吗$|^为什么|^如何|^怎么", t))),
    "separator": ("分隔符/冒号", lambda t: bool(re.search(r"[丨|｜]|[:：]", t))),
    "recency": ("时效/实测", lambda t: bool(re.search(r"(亲测|实测|最新|刚|今天|20\d\d|\d+\.\d+)", t))),
}


#: 标题「原型」——比单个特征更能解释流量，因为它对应的是读者点开后的预期。
ARCHETYPES: dict[str, tuple[str, str]] = {
    "listing": ("清单/资源", r"(TOP|top|\d+\s*(个|件|期|步)|清单|盘点|合集|推荐|newsletter)"),
    "diary": ("个人体验/复盘", r"(亲测|\d+\s*(天|个月)|之后|我得到|我从不|我开始|我的)"),
    "brief": ("资讯简报/日报", r"(日间版|早报|日报|每日动态|要闻速览|资讯｜|资讯\|)"),
    "ask": ("提问/求推荐", r"(求推|求推荐|大家.*怎么|该不该|严肃请教|有.*吗[？?]?$|吗$)"),
}


def archetype(title: str) -> str:
    """先判简报（形态最特殊），再判提问、清单、个人体验，其余归到观点/诊断。"""
    for key in ("brief", "ask", "listing", "diary"):
        label, pattern = ARCHETYPES[key]
        if re.search(pattern, title):
            return label
    return "观点/诊断"


def _num(raw: Any) -> int:
    """小红书互动数是 '1.2万' / '赞' 这类脏字符串。"""
    text = str(raw or "0").strip()
    if text.endswith("万"):
        try:
            return int(float(text[:-1]) * 10000)
        except ValueError:
            return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def load_needs(path: Path = XLSX) -> list[dict[str, Any]]:
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True)
    sheet = book["市场需求痛点分类"]
    rows: list[dict[str, Any]] = []
    kind = ""
    for raw in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=11, values_only=True):
        if not any(raw):
            continue
        if raw[0]:
            kind = str(raw[0]).strip()
        if not raw[1]:
            continue
        rows.append(
            {
                "id": str(raw[1]).strip(),
                "kind": kind,
                "title": str(raw[2] or "").strip(),
                "scenario": str(raw[3] or "").strip(),
                "need": str(raw[4] or "").strip(),
                "pain": str(raw[5] or "").strip(),
                "workaround": str(raw[6] or "").strip(),
                "outcome": str(raw[7] or "").strip(),
                "boundary": str(raw[8] or "").strip(),
                "script": str(raw[9] or "").strip(),
                "case": str(raw[10] or "").strip(),
            }
        )
    return rows


def tag_segments(need: dict[str, Any]) -> list[str]:
    """按场景/需求/痛点里的词判断这条需求服务哪几类人。"""
    blob = " ".join(str(need.get(k) or "") for k in ("scenario", "need", "pain", "workaround"))
    hits = []
    for key, meta in SEGMENTS.items():
        if any(cue in blob for cue in meta["cue"]):
            hits.append(key)
    return hits


def load_notes(path: Path = NOTES) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def analyse() -> dict[str, Any]:
    needs = load_needs()
    notes = load_notes()

    # 需求侧：按类型聚，并给每条打人群标签
    by_kind: dict[str, list[str]] = {}
    for need in needs:
        need["segments"] = tag_segments(need)
        by_kind.setdefault(need["kind"], []).append(need["id"])
    tagged = [n for n in needs if n["segments"]]
    untagged = [n["id"] for n in needs if not n["segments"]]

    # 人 × 需求类型 覆盖表
    kinds = list(by_kind)
    grid: dict[str, dict[str, list[str]]] = {}
    for seg in SEGMENTS:
        grid[seg] = {kind: [n["id"] for n in needs if n["kind"] == kind and seg in n["segments"]] for kind in kinds}

    # 供给侧：每个搜索词的中位点赞
    per_keyword: dict[str, list[int]] = {}
    for note in notes:
        per_keyword.setdefault(str(note.get("keyword") or ""), []).append(_num(note.get("liked_count")))
    keyword_stats = {
        key: {"n": len(vals), "median": st.median(vals), "max": max(vals)} for key, vals in per_keyword.items()
    }

    # 表达侧：结构特征 vs 中位点赞
    titled = [(str(n.get("title") or "").strip(), _num(n.get("liked_count"))) for n in notes]
    titled = [(t, likes) for t, likes in titled if t]
    base = st.median([likes for _, likes in titled]) if titled else 0
    features = []
    for key, (label, test) in FEATURES.items():
        hits = [likes for text, likes in titled if test(text)]
        if not hits:
            continue
        features.append(
            {
                "key": key,
                "label": label,
                "n": len(hits),
                "median": st.median(hits),
                "mean": round(st.mean(hits)),
                "lift": round(st.median(hits) / base, 2) if base else 0,
            }
        )
    features.sort(key=lambda row: -row["median"])

    # 原型：跨关键词比较，再在每个大词内部验一遍（防止是关键词差异伪装的）
    per_arch: dict[str, list[int]] = {}
    for text, likes in titled:
        per_arch.setdefault(archetype(text), []).append(likes)
    archetypes = sorted(
        (
            {"label": key, "n": len(vals), "median": st.median(vals), "lift": round(st.median(vals) / base, 2) if base else 0}
            for key, vals in per_arch.items()
        ),
        key=lambda row: -row["median"],
    )

    stratified: dict[str, dict[str, dict[str, float]]] = {}
    for keyword in ("信息过载", "刷手机无聊", "戒短视频"):
        subset = [
            (str(note.get("title") or "").strip(), _num(note.get("liked_count")))
            for note in notes
            if str(note.get("keyword") or "") == keyword and str(note.get("title") or "").strip()
        ]
        if not subset:
            continue
        floor = st.median([likes for _, likes in subset])
        buckets: dict[str, list[int]] = {}
        for text, likes in subset:
            buckets.setdefault(archetype(text), []).append(likes)
        stratified[keyword] = {
            label: {"n": len(vals), "median": st.median(vals), "lift": round(st.median(vals) / floor, 2)}
            for label, vals in buckets.items()
        }

    # 评论/赞：早播要的是「会自己开口」的人，不是默默点赞的人
    engaged = [
        (str(n.get("title") or "").strip() or "（无标题）", _num(n.get("liked_count")), _num(n.get("comment_count")))
        for n in notes
        if _num(n.get("liked_count")) >= 200
    ]
    ratios = sorted(
        (
            {"title": t, "likes": likes, "comments": cmts, "ratio": round(cmts / likes, 3)}
            for t, likes, cmts in engaged
        ),
        key=lambda row: -row["ratio"],
    )

    return {
        "generated": "2026-11-12",
        "need_count": len(needs),
        "need_kinds": by_kind,
        "needs": needs,
        "untagged_needs": untagged,
        "segment_coverage": grid,
        "notes": {"n": len(notes), "titled": len(titled), "base_median_likes": base},
        "keyword_stats": keyword_stats,
        "features": features,
        "archetypes": archetypes,
        "stratified": stratified,
        "comment_ratio": {
            "n": len(ratios),
            "median_ratio": st.median([r["ratio"] for r in ratios]),
            "top": ratios[:12],
            "bottom": ratios[-6:],
        },
        "top_notes": [
            {"likes": likes, "title": text}
            for text, likes in sorted(titled, key=lambda pair: -pair[1])[:15]
        ],
    }


def main() -> None:
    data = analyse()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"需求 {data['need_count']} 条 / 类型 {len(data['need_kinds'])} 类")
    print(f"未打上人群标签：{data['untagged_needs']}")
    for seg, row in data["segment_coverage"].items():
        ids = [i for ids in row.values() for i in ids]
        print(f"  {seg}: {len(ids)} 条 -> {ids}")
    print(f"\n笔记 {data['notes']['n']} 条（有标题 {data['notes']['titled']}），中位赞 {data['notes']['base_median_likes']:.0f}")
    print(f"{'特征':12s}{'条数':>5s}{'中位赞':>9s}{'倍数':>7s}")
    for row in data["features"]:
        print(f"{row['label']:12s}{row['n']:5d}{row['median']:9.0f}{row['lift']:7.2f}")
    print(f"\n{'原型':16s}{'条数':>5s}{'中位赞':>9s}{'倍数':>7s}")
    for row in data["archetypes"]:
        print(f"{row['label']:16s}{row['n']:5d}{row['median']:9.0f}{row['lift']:7.2f}")
    print(f"\n评论/赞 中位 {data['comment_ratio']['median_ratio']:.3f}（n={data['comment_ratio']['n']}）")
    print(f"已写入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
