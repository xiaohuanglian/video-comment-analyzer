"""tests/test_annotation_score.py"""

import csv

import pytest

from tools import annotation_score

COLS = [
    "编号",
    "创作者",
    "视频",
    "视频ID",
    "步序",
    "系统判定动作",
    "动作名",
    "判定标准",
    "引用原文",
    "中文翻译",
    "人工判定",
    "人工应标动作",
]


def _row(n, move, label, verdict, claimed=""):
    return {
        "编号": str(n),
        "创作者": "Jillz Guerin",
        "视频": "t",
        "视频ID": "v1",
        "步序": str(n),
        "系统判定动作": move,
        "动作名": label,
        "判定标准": "x",
        "引用原文": "q",
        "中文翻译": "译",
        "人工判定": verdict,
        "人工应标动作": claimed,
    }


def _write(tmp_path, rows):
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_score_counts_only_filled_rows(tmp_path):
    path = _write(
        tmp_path,
        [
            _row(1, "give_mechanism", "给机制", "对"),
            _row(2, "give_mechanism", "给机制", "错", "give_example"),
            _row(3, "verdict", "下判断", ""),  # 未填，不计入分母
        ],
    )
    result = annotation_score.score(annotation_score.read_rows(path))
    assert result["graded"] == 2
    assert result["skipped"] == 1
    assert result["human_consistency"] == 0.5


def test_score_breaks_down_by_move_and_confusions(tmp_path):
    path = _write(
        tmp_path,
        [
            _row(1, "give_mechanism", "给机制", "对"),
            _row(2, "give_mechanism", "给机制", "错", "give_example"),
            _row(3, "verdict", "下判断", "错", "verdict"),  # 同动作，不算混淆
            _row(4, "verdict", "下判断", "错", "contrarian_claim"),
        ],
    )
    result = annotation_score.score(annotation_score.read_rows(path))
    per_move = {item["move"]: item for item in result["per_move"]}
    assert per_move["give_mechanism"]["ratio"] == 0.5
    assert per_move["verdict"]["ratio"] == 0.0
    # 排序：ratio 低在前
    assert result["per_move"][0]["move"] == "verdict"
    assert {(c["system"], c["human"]) for c in result["confusions"]} == {
        ("give_mechanism", "give_example"),
        ("verdict", "contrarian_claim"),
    }


def test_empty_annotation_reports_nothing_graded(tmp_path):
    path = _write(tmp_path, [_row(1, "verdict", "下判断", "")])
    result = annotation_score.score(annotation_score.read_rows(path))
    assert result["graded"] == 0
    assert result["human_consistency"] is None
    assert "还没有填写" in annotation_score.render(result)


def test_render_compares_with_system_overall(tmp_path):
    path = _write(tmp_path, [_row(1, "verdict", "下判断", "对"), _row(2, "verdict", "下判断", "错")])
    result = annotation_score.score(annotation_score.read_rows(path))
    text = annotation_score.render(result, system_overall=0.67)
    assert "0.5" in text
    assert "差距：-0.17" in text


@pytest.mark.parametrize("raw,expected", [("对", "right"), ("✓", "right"), ("错", "wrong"), ("", ""), ("嗯", "")])
def test_verdict_normalization(raw, expected):
    assert annotation_score._norm(raw) == expected


def test_cli_missing_file(tmp_path, capsys):
    assert annotation_score.main([str(tmp_path / "nope.csv")]) == 2
    assert "找不到文件" in capsys.readouterr().err
