"""把「早播小红书用户需求画像.xlsx」里内嵌的案例截图解析出来，并核对案例覆盖情况。

背景：openpyxl 的 ``ws._images[i].path`` 对这本工作簿一律返回 ``/xl/media/image1.png``，
不可信；必须自己读 ``xl/drawings/drawing1.xml`` 的锚点（xdr:col / xdr:row）再去
``xl/drawings/_rels/drawing1.xml.rels`` 里查 r:embed，才能知道某张图挂在哪一行。
不知道这一点时，曾把 A02 的图错记成 A01、把 B04 的图错记成 B03。

另一个坑：所有 ``.jpeg`` 实际是 PNG 字节，直接按扩展名当 JPEG 读会报
"the .jpeg extension declares image/jpeg, but the bytes use a different image format"。
这里统一按 magic bytes 复制成 ``.png``。

用法：
    uv run python scripts/zaobo_cases.py            # 解析并打印覆盖体检
    uv run python scripts/zaobo_cases.py --extract  # 另外把图导到 /tmp/zaobo_cases
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "docs/早播/早播小红书用户需求画像.xlsx"
OUT = ROOT / "data/早播/cases.json"
EXTRACT_DIR = Path("/tmp/zaobo_cases")

_SHEET = "市场需求痛点分类"
_COL_CODE, _COL_CASE = 2, 11
_FIRST_ROW, _LAST_ROW = 2, 17

# 档案 research_goal 的验证顺序：A 类先验，B 类次之，C/D 类按表内判定为弱匹配（用于排除）。
_RESEARCH_ORDER = {"A": 0, "B": 1, "C": 2, "D": 2}


def _anchor_rows(xlsx: Path) -> list[dict]:
    """返回 [{excel_row, code, media, col}]；excel_row 为 1-based 行号。"""
    with zipfile.ZipFile(xlsx) as z:
        drawing = z.read("xl/drawings/drawing1.xml").decode("utf-8")
        rels = z.read("xl/drawings/_rels/drawing1.xml.rels").decode("utf-8")
        rel_map = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))

    wb = openpyxl.load_workbook(xlsx, read_only=True)
    ws = wb[_SHEET]

    blocks = re.findall(
        r"<xdr:oneCellAnchor.*?</xdr:oneCellAnchor>|<xdr:twoCellAnchor.*?</xdr:twoCellAnchor>",
        drawing,
        re.S,
    )
    found = []
    for block in blocks:
        col = int(re.search(r"<xdr:col>(\d+)</xdr:col>", block).group(1)) + 1
        row0 = int(re.search(r"<xdr:row>(\d+)</xdr:row>", block).group(1))
        embed = re.search(r'r:embed="(rId\d+)"', block).group(1)
        excel_row = row0 + 1  # xdr 是 0-based，Excel 是 1-based
        code = ws.cell(row=excel_row, column=_COL_CODE).value
        media = rel_map.get(embed, "?").split("/")[-1]
        found.append(
            {"excel_row": excel_row, "code": code or "", "media": media, "col": col}
        )
    wb.close()
    return sorted(found, key=lambda r: (r["code"], r["col"]))


def _needs() -> list[dict]:
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb[_SHEET]
    rows = []
    for r in range(_FIRST_ROW, _LAST_ROW + 1):
        code = ws.cell(row=r, column=2).value
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "type": ws.cell(row=r, column=1).value or "",
                "need": ws.cell(row=r, column=3).value or "",
                "scene": ws.cell(row=r, column=4).value or "",
                "pain": ws.cell(row=r, column=6).value or "",
                "boundary": ws.cell(row=r, column=9).value or "",
            }
        )
    wb.close()
    return rows


def _extract(xlsx: Path, names: set[str]) -> list[str]:
    saved = []
    media_dir = EXTRACT_DIR / "xl/media"
    fix_dir = EXTRACT_DIR / "fix"
    media_dir.mkdir(parents=True, exist_ok=True)
    fix_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(xlsx) as z:
        for name in z.namelist():
            if not name.startswith("xl/media/") or name.split("/")[-1] not in names:
                continue
            raw = z.read(name)
            (media_dir / name.split("/")[-1]).write_bytes(raw)
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            elif raw[:2] == b"\xff\xd8":
                ext = ".jpg"
            else:
                ext = ".bin"
            dest = fix_dir / (Path(name).stem + ext)
            dest.write_bytes(raw)
            saved.append(str(dest))
    return saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true", help="导出图片到 /tmp/zaobo_cases")
    args = ap.parse_args()

    needs = _needs()
    anchors = _anchor_rows(XLSX)
    by_code: dict[str, list[str]] = {}
    for a in anchors:
        by_code.setdefault(a["code"], []).append(a["media"])

    rows = []
    for n in needs:
        imgs = by_code.get(n["code"], [])
        rows.append(
            {
                **n,
                "cases": imgs,
                "case_count": len(imgs),
                "research_priority": _RESEARCH_ORDER.get(n["code"][0], 9),
            }
        )

    have = [r for r in rows if r["case_count"]]
    lack = [r for r in rows if not r["case_count"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"needs": rows, "anchor_count": len(anchors)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"需求 {len(rows)} 条；内嵌截图 {len(anchors)} 张，覆盖 {len(have)} 条需求")
    print(f"\n有案例（{len(have)} 条）：")
    for r in have:
        print(f"  {r['code']} {r['need']}  ← {', '.join(r['cases'])}")
    print(f"\n无案例（{len(lack)} 条）：")
    for r in lack:
        tag = "【档案要求先验】" if r["research_priority"] <= 1 else ""
        print(f"  {r['code']} {r['need']}{tag}")

    low = sum(1 for r in lack if r["research_priority"] == 0)
    high = sum(1 for r in have if r["research_priority"] >= 2)
    print(
        f"\n错配：A 类无案例 {low} 条 / C、D 类（判定弱匹配）却有案例 {high} 条"
    )

    if args.extract:
        saved = _extract(XLSX, {a["media"] for a in anchors})
        print(f"\n已导出 {len(saved)} 张到 {EXTRACT_DIR}/fix/")
    print(f"\n写入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
