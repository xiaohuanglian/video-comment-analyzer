# -*- coding: utf-8 -*-
"""Checkpoint C tests: open theme clustering."""

from __future__ import annotations

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run, load_themes
from api.services.insight.theme_clustering import collect_raw_signals, compute_theme_stats, run_theme_clustering
from api.services.insight.theme_schemas import ThemeRecord


SAMPLE = """comment_id,content,user_id,nickname
1,看不懂镜像，左右腿分不清,u1,用户1
2,视频镜像把我搞晕了，不知道跟同侧还是反侧,u2,用户2
3,谢谢教练,u3,用户3
4,膝盖旧伤还能练吗,u4,用户4
"""


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频_BV1test" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE, encoding="utf-8")
    rel = "健身类/博主/视频_BV1test/comments_2026-07-19.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    records = ingest_files([rel])
    run_id = "cpc_test"
    create_run(
        RunConfig(
            run_id=run_id,
            name="cpc",
            file_paths=[rel],
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
            created_at="2026-07-19T00:00:00Z",
        ),
        records,
    )
    run_analysis_batch(run_id, use_mock=True)
    return run_id


def test_collect_raw_signals_dedupes(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    signals = collect_raw_signals(load_results(run_id))
    texts = " ".join(item.text for item in signals)
    assert "镜像" in texts
    assert len(signals) >= 1


def test_mock_theme_clustering_writes_themes_json(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    doc = run_theme_clustering(run_id, use_mock=True)
    assert doc.raw_signal_count >= 1
    assert doc.themes
    saved = load_themes(run_id)
    assert saved.themes
    assert saved.themes[0].stats.comment_count >= 1
    assert saved.themes[0].record_ids


def test_theme_stats_from_signal_ids(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    signals = collect_raw_signals(load_results(run_id))
    theme = ThemeRecord(
        theme_id="t_test",
        theme_name="镜像方向",
        theme_type="new_barrier",
        definition="测试",
        included_signal_ids=[signals[0].signal_id],
    )
    stats = compute_theme_stats(theme, signals)
    assert stats.comment_count == 1
    assert theme.record_ids
