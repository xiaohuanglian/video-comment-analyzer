"""Code-only quality gates for hybrid themes."""

from __future__ import annotations

from typing import Dict, List


def validate_theme_document(document, known_signal_ids: set[str], known_record_ids: set[str]) -> Dict:
    warnings: List[str] = []
    seen = set()
    covered = set()
    for theme in document.themes:
        if not theme.included_signal_ids or not theme.record_ids:
            warnings.append(f"{theme.theme_id}: 缺少信号或评论证据")
        for signal_id in theme.included_signal_ids:
            if signal_id not in known_signal_ids:
                warnings.append(f"{theme.theme_id}: 不存在的 signal_id {signal_id}")
            if signal_id in seen:
                warnings.append(f"{theme.theme_id}: signal_id 重复归属 {signal_id}")
            seen.add(signal_id)
            covered.add(signal_id)
        for record_id in theme.record_ids:
            if record_id not in known_record_ids:
                warnings.append(f"{theme.theme_id}: 不存在的 record_id {record_id}")
    return {
        "signal_count": len(known_signal_ids),
        "clustered_signal_count": len(covered),
        "coverage": round(len(covered) / max(1, len(known_signal_ids)), 4),
        "warning_count": len(warnings),
        "warnings": warnings,
    }
