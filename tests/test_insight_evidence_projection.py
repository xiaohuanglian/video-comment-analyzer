# -*- coding: utf-8 -*-
"""Raw-dict evidence indexing and source projection for large runs."""

from __future__ import annotations

import json

from api.services.insight.evidence_schemas import (
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    ItemCertainty,
    PrimaryExpression,
    RecordStatus,
    SpeakerScope,
)
from api.services.insight.research_agent import _index_evidence_items


def _card() -> EvidenceCard:
    return EvidenceCard(
        record_id="r1",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.QUESTION,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="动作疑问",
                evidence_quote="这个动作怎么做？",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            )
        ],
    )


def test_index_assigns_stable_ids_from_raw_dicts():
    raw = _card().model_dump(mode="json")
    index = _index_evidence_items([{"record_id": "r1", "card": raw}])
    assert "r1::e0" in index
    item = index["r1::e0"]
    assert item["type"] == "problem"
    assert item["speaker_scope"] == "self"
    assert item["certainty"] == "high"
    assert item["evidence_quote"] == "这个动作怎么做？"


def test_load_evidence_cards_can_drop_source(tmp_path, monkeypatch):
    import api.services.insight.storage as st

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "evidence_cards.jsonl").write_text(
        json.dumps(
            {
                "record_id": "r1",
                "source": {"comment_text": "hello"},
                "card": {"record_id": "r1", "evidence_items": []},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(st, "run_dir_for_id", lambda rid: run_dir)

    full = st.load_evidence_cards("run")
    assert full[0]["source"]["comment_text"] == "hello"

    lean = st.load_evidence_cards("run", include_source=False)
    assert "source" not in lean[0]
    assert lean[0]["card"]["record_id"] == "r1"