# -*- coding: utf-8 -*-
"""Stratified sampling for trial runs."""

from __future__ import annotations

import random
from typing import Dict, List, Sequence, Tuple

from .schemas import SourceRecord

DEFAULT_SAMPLE_SEED = 42


def _length_bucket(text: str) -> str:
    length = len(text.strip())
    if length < 20:
        return "short"
    if length <= 80:
        return "medium"
    return "long"


def _stratum_key(record: SourceRecord) -> Tuple[str, str, str]:
    return (record.source_file, record.creator_type or "未知", _length_bucket(record.comment_text))


def stratified_sample(
    records: Sequence[SourceRecord],
    sample_size: int,
    *,
    seed: int = DEFAULT_SAMPLE_SEED,
) -> List[str]:
    """Return internal_record_id list; reproducible stratified sample."""
    if sample_size <= 0:
        return []
    if sample_size >= len(records):
        return [record.internal_record_id for record in records]

    rng = random.Random(seed)
    buckets: Dict[Tuple[str, str, str], List[SourceRecord]] = {}
    for record in records:
        buckets.setdefault(_stratum_key(record), []).append(record)

    for bucket in buckets.values():
        rng.shuffle(bucket)

    bucket_keys = list(buckets.keys())
    rng.shuffle(bucket_keys)

    selected: List[str] = []
    selected_set: set[str] = set()
    bucket_index = 0

    while len(selected) < sample_size and bucket_keys:
        key = bucket_keys[bucket_index % len(bucket_keys)]
        bucket = buckets[key]
        while bucket and bucket[0].internal_record_id in selected_set:
            bucket.pop(0)
        if bucket:
            record = bucket.pop(0)
            selected.append(record.internal_record_id)
            selected_set.add(record.internal_record_id)
        else:
            bucket_keys = [k for k in bucket_keys if buckets[k]]
            if not bucket_keys:
                break
            bucket_index = 0
            continue
        bucket_index += 1

    if len(selected) < sample_size:
        remaining = [r.internal_record_id for r in records if r.internal_record_id not in selected_set]
        rng.shuffle(remaining)
        selected.extend(remaining[: sample_size - len(selected)])

    return selected
