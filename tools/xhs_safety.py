# -*- coding: utf-8 -*-
"""兼容门面：夜间静默 + 搜索配额的真实实现搬到了 ``tools/crawl_safety.py``。

这两条规则（「真人要睡觉」「一天不能问太多不相关的话题」）跟平台无关，
抖音要和小红书接同一套约束。如果继续把它们写在这个带 xhs 名字的文件里，
日后没人敢改（一改就怕碰坏小红书），抖音那边就只能复制一份逻辑。

这里保留原有的模块名与函数签名，老调用方（``main.py``、``media_platform/xhs/core.py``、
``scripts/xhs_keyword_notes.py``、测试）一行不用改；新代码请直接 import
``tools.crawl_safety``。
"""

from __future__ import annotations

from tools.crawl_safety import (  # noqa: F401  (re-export)
    QuietHoursActive,
    SearchBudget,
    SearchBudgetExceeded,
    daily_search_limit,
    ensure_batch_allowed,
    ensure_not_quiet_hours,
    format_seconds,
    in_quiet_hours,
    max_keywords_per_batch,
    plan_keywords,
    quiet_hours,
    reset_search_budget,
    search_budget,
    seconds_until_quiet_end,
)

__all__ = [
    "QuietHoursActive",
    "SearchBudget",
    "SearchBudgetExceeded",
    "daily_search_limit",
    "ensure_batch_allowed",
    "ensure_not_quiet_hours",
    "format_seconds",
    "in_quiet_hours",
    "max_keywords_per_batch",
    "plan_keywords",
    "quiet_hours",
    "reset_search_budget",
    "search_budget",
    "seconds_until_quiet_end",
]
