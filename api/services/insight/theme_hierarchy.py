"""Conservative hierarchy adapter for hybrid themes."""

from __future__ import annotations

from collections import defaultdict


def build_fallback_hierarchy(themes):
    """Group only for presentation; never changes a theme's evidence membership."""
    groups = defaultdict(list)
    for theme in themes:
        groups[theme.theme_type or "other"].append(theme.theme_id)
    return {
        "top_level_themes": [
            {"theme_id": f"top_{kind}", "theme_name": kind, "child_theme_ids": ids}
            for kind, ids in sorted(groups.items())
        ]
    }
