from api.services.insight.theme_signal_preprocess import normalize_theme_signal, prepare_theme_signals


def test_normalize_keeps_negation_and_direction():
    assert normalize_theme_signal("  不知道　左旋？？  ") == "不知道 左旋?"


def test_prepare_merges_exact_video_duplicates():
    rows = [
        {
            "record_id": "r1",
            "source": {"source_file": "a.csv", "user_id": "u1"},
            "analysis": {
                "new_signals": [
                    {"type": "new_problem", "text": "不知道 左旋？", "evidence_quote": "不知道 左旋"}
                ]
            },
        },
        {
            "record_id": "r2",
            "source": {"source_file": "a.csv", "user_id": "u2"},
            "analysis": {
                "new_signals": [
                    {"type": "new_problem", "text": "不知道　左旋？？", "evidence_quote": "不知道 左旋"}
                ]
            },
        },
    ]
    prepared = prepare_theme_signals(rows)
    assert len(prepared) == 1
    assert prepared[0].frequency == 2
    assert prepared[0].user_count == 2
    assert len(prepared[0].record_ids) == 2
