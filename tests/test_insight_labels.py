# -*- coding: utf-8 -*-
"""Contactability and label tests."""

from api.services.insight.field_mapping import resolve_source_links
from api.services.insight.labels import label_signal
from api.services.insight.statistics import contactability


def test_resolve_bilibili_homepage_from_raw_data():
    source = {
        "platform": "unknown",
        "user_id": "1944301400",
        "user_homepage_url": "",
        "comment_url": "",
        "source_file": "健身类/戴夫健身/「_SpineCare_」如何纠正骨盆旋_BV1U64y1Q76K/comments_2026-07-18.csv",
        "raw_data": {"video_id": "759022531", "comment_id": "221823890672"},
    }
    homepage, comment_url = resolve_source_links(source)
    assert homepage == "https://space.bilibili.com/1944301400"
    assert comment_url == "https://www.bilibili.com/video/759022531#reply221823890672"
    assert contactability(source) == "high"


def test_signal_labels_cover_prompt_enum():
    from api.services.insight.prompts import SIGNAL_ENUM

    for key in SIGNAL_ENUM:
        assert label_signal(key) != key
