# -*- coding: utf-8 -*-
"""YouVibe 数据查询:工作台内嵌 youvibe-analytics-query 能力。

实现方式:写临时请求文件 → subprocess 调 scripts/query.py → 返回 JSON。
只支持无需管理员凭证的 App 分析 / Web 埋点接口;管理后台接口需交互式
输入账号密码,不在工作台无人值守环境里开放。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / "tools" / "youvibe-analytics-query"
QUERY_SCRIPT = SKILL_DIR / "scripts" / "query.py"

# 无需管理员凭证、可在工作台直接跑的接口别名
OPEN_ENDPOINTS = [
    "app_dau",
    "app_dau_users",
    "app_audit_users",
    "app_retention",
    "app_retention_detail",
    "app_retention_activity",
    "app_longterm_discover",
    "app_longterm_discover_users",
    "app_longterm_list",
    "app_user_behavior",
    "app_user_behavior_detail",
    "app_user_profile",
    "app_user_comments",
    "web_events_query",
    "events_catalog",
]

# 需要管理员凭证的(管理后台),工作台不开放
ADMIN_ENDPOINTS = [
    "dashboard",
    "engagement",
    "interactions",
    "supply",
    "supply_trend",
    "depth",
    "content",
    "content_top",
    "new_devices",
    "retention",
    "content_journey",
    "events_query",
    "content_metrics",
    "content_summary",
    "content_trend",
    "content_comparison",
    "content_author_table",
    "content_table",
    "content_detail",
]


async def run_queries(queries: list[dict[str, Any]], timeout: float = 120) -> dict[str, Any]:
    """执行一批查询。queries: [{name, endpoint, params}]。失败抛异常。"""
    if not queries:
        raise ValueError("queries 不能为空")
    if len(queries) > 8:
        raise ValueError("每批最多 8 个请求")
    for q in queries:
        ep = q.get("endpoint", "")
        if ep not in OPEN_ENDPOINTS:
            raise ValueError(
                f"endpoint「{ep}」工作台不开放(需管理员凭证或不存在)。"
                f"可用:{', '.join(OPEN_ENDPOINTS)}"
            )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"queries": queries}, f, ensure_ascii=False)
        req_path = Path(f.name)

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            str(QUERY_SCRIPT),
            "--requests-file",
            str(req_path),
            cwd=str(SKILL_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"查询超时(>{timeout:.0f}s)") from None
        if proc.returncode != 0:
            raise RuntimeError(
                f"查询脚本失败(exit {proc.returncode}):{stderr.decode('utf-8', 'ignore')[:400]}"
            )
        return json.loads(stdout.decode("utf-8"))
    finally:
        req_path.unlink(missing_ok=True)
