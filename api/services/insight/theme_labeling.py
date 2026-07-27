"""Short-schema label helpers; failures must not stop the hybrid pipeline."""

from __future__ import annotations

from collections import Counter


def keyword_fallback_label(representative_texts: list[str]) -> dict:
    tokens = Counter(
        token
        for text in representative_texts
        for token in (text or "").split()
        if len(token) >= 2
    )
    name = "／".join(token for token, _ in tokens.most_common(2)) or "待复核主题"
    return {
        "theme_name": name[:20],
        "definition": f"围绕「{name[:40]}」的用户信号",
        "label_source": "keyword_fallback",
        "review_status": "pending",
    }
