import numpy as np

from api.services.insight.theme_local_clustering import cluster_video_signals, dynamic_min_cluster_size
from api.services.insight.theme_signal_preprocess import PreparedThemeSignal


def _signal(index: int, text: str) -> PreparedThemeSignal:
    return PreparedThemeSignal(
        prepared_id=f"p{index}",
        source_file="video.csv",
        normalized_text=text,
        original_text=text,
        signal_type="new_problem",
        frequency=1,
        user_keys={f"u{index}"},
        signal_ids=[f"s{index}"],
        record_ids=[f"r{index}"],
    )


def test_dynamic_cluster_size_ranges():
    assert dynamic_min_cluster_size(499) == 5
    assert dynamic_min_cluster_size(500) == 8
    assert dynamic_min_cluster_size(2000) == 12


def test_small_video_preserves_noise_without_forcing_cluster():
    signals = [_signal(i, f"信号{i}") for i in range(4)]
    embeddings = np.eye(4, dtype=np.float32)
    result = cluster_video_signals("v1", signals, embeddings)
    assert result["clusters"] == []
    assert result["unclustered_indexes"] == [0, 1, 2, 3]
