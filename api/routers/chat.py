# -*- coding: utf-8 -*-
"""首页对话 API:持久化历史 + 代理到 LLM 网关。

LLM 走 OpenAI 兼容网关,配置见环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。
内网网关必须 trust_env=False 避开系统代理。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.llm import complete

router = APIRouter(prefix="/chat", tags=["chat"])

CHAT_DIR = Path(__file__).resolve().parents[2] / "data" / "chat"
HISTORY_FILE = CHAT_DIR / "history.json"

SYSTEM_PROMPT = (
    "你是「评论工作台」的 AI 助手,一个社媒评论运营工具的内置对话入口。"
    "你要基于下面注入的项目知识回答,把自己当成这个项目的负责人,不要说「我看不到」。"
    "核心红线:AI 只发现与起草,人负责确认与发送。"
    "用户会通过你布置任务(比如「采集 xxx 关键词的评论」「看看有什么待处理的」)。"
    "如果用户的要求需要执行动作,先确认理解并说明将怎么做;如果只是在了解状态,直接回答。"
    "\n\n交互风格 = 得力下属服务老板:\n"
    "- 给选择必须编号+换行,用户回一个数字就行\n"
    "- 能给选项就别让用户打字;替他想好下一步,标(推荐)\n"
    "- 全程人话,不提接口名/参数/文件路径\n"
    "- 用户熟了会直接下指令(『筛20条』『把那批拒了』『写第3条』)→ 照做,不重述流程\n"
    "- 执行完汇报结果,顺手给下一步选项\n"
    "工作台已内嵌 YouVibe 数据查询(App 日活/留存/行为、Web 埋点,接口 POST /api/youvibe/query,"
    "别名清单见 GET /api/youvibe/endpoints;管理后台类接口需管理员凭证未开放)。"
    "用户问 YouVibe 产品数据时,告诉他可以去「设置」页下方查询,或说明你能查哪类。"
    "回答用中文,简洁,不堆砌。"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_doc(rel: str, max_chars: int = 2500) -> str:
    """读项目档案文件,截断防超 token。"""
    try:
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]
    except OSError:
        return ""


def _audience_context() -> str:
    """注入 youvibe 受众画像(growth 飞轮产出的 segment_reports + 产品档案)。"""
    parts: list[str] = []
    try:
        from api.services.growth.seeds import BUILTIN_PRODUCTS

        p = BUILTIN_PRODUCTS.get("youvibe")
        if p:
            parts.append(
                "【产品档案 YouVibe】"
                f"领域:{p.domain};增长目标:{p.growth_goal};"
                f"目标用户:{p.target_audience};"
                f"价值主张:{'、'.join(p.value_props)};"
                f"定位状态:{p.positioning_status};"
                f"禁用宣称:{p.forbidden_claims}"
            )
    except Exception:
        pass
    try:
        reports = json.loads(
            (PROJECT_ROOT / "data" / "growth" / "youvibe" / "segment_reports.json").read_text(
                encoding="utf-8"
            )
        )
        if reports:
            segs = reports[-1].get("segments", [])
            lines = [
                f"- {s.get('name')}:核心需求 {'、'.join((s.get('core_needs') or [])[:3])};"
                f"产品契合度 {s.get('product_fit', '?')}"
                for s in segs[:6]
            ]
            parts.append(
                f"【受众画像(基于真实评论信号聚类,共 {len(reports)} 份报告,以下最新)】\n"
                + "\n".join(lines)
            )
    except Exception:
        pass
    return "\n\n".join(parts)


def _project_context() -> str:
    """把项目理解注入 system:档案文档 + 自动化配置(含关键词)+ 采集状态。"""
    parts: list[str] = []
    state = _read_doc("PROJECT_STATE.md")
    if state:
        parts.append(f"【项目档案 PROJECT_STATE.md】\n{state}")
    try:
        from api.services.outreach import reply_automation as auto

        cfg = auto.get_store().config
        parts.append(
            "【回复自动化配置】"
            f"关键词:{'、'.join(cfg.get('keywords', []))};"
            f"每日发送上限:{cfg.get('daily_send_limit')};"
            f"发送窗口:{cfg.get('send_window_start')}-{cfg.get('send_window_end')};"
            f"新鲜度 A 档 ≤{cfg.get('freshness_a_hours')}h、B 档 ≤{cfg.get('freshness_b_hours')}h;"
            f"自动定时采集(auto_collect):{cfg.get('auto_collect', False)}(已关闭,走手动批量采集)。"
            f"注意:这组关键词就是当前采集/筛选用的目标词;「采集」页手动批量采集时用户也可以临时输入别的词,那些是一次性的,不需要另查。"
        )
    except Exception:
        pass
    try:
        from api.services import crawler_manager

        st = crawler_manager.get_status()
        parts.append(f"【采集器状态】{st}")
    except Exception:
        pass
    return "\n\n".join(parts)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    ts: float = 0


class SendRequest(BaseModel):
    text: str


def _load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(items: list[dict[str, Any]]) -> None:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(items[-500:], ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _automation_context() -> str:
    """把自动化当前状态注入 system,让 AI 能回答「有什么待处理」。"""
    try:
        from api.services.outreach import reply_automation as auto

        store = auto.get_store()
        items = store.items
        funnel = {
            s: sum(1 for i in items if i["status"] == s)
            for s in ("pending_review", "approved", "sent", "failed", "rejected")
        }
        cycle = store._state.get("cycle", {})
        return (
            f"\n\n当前自动化实时状态:待批准 {funnel['pending_review']} 条,"
            f"已批准待发送 {funnel['approved']} 条,已发送 {funnel['sent']} 条,"
            f"失败 {funnel['failed']} 条。"
            f"采集循环运行中:{cycle.get('running', False)}(自动定时采集已按设计关闭,不要再提 subprocess 报错,那个 bug 已修复),"
            f"上次筛选/采集:{cycle.get('last_summary') or '无'},"
            f"最近错误:{cycle.get('last_error') or '无'}。"
        )
    except Exception:
        return ""


@router.get("/history")
async def history(limit: int = 200) -> list[dict[str, Any]]:
    return _load_history()[-limit:]


@router.post("/clear")
async def clear() -> dict[str, bool]:
    _save_history([])
    return {"ok": True}


@router.post("/send")
async def send(body: SendRequest) -> dict[str, Any]:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    history = _load_history()
    user_msg = {"role": "user", "text": text, "ts": time.time()}
    history.append(user_msg)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\n\n"
            + _project_context()
            + "\n\n"
            + _audience_context()
            + _automation_context(),
        }
    ]
    for m in history[-40:]:
        messages.append({"role": m["role"], "content": m["text"]})

    try:
        reply = await complete(messages, temperature=0.7, timeout=60, feature="chat") or "(模型返回为空)"
    except Exception as e:  # noqa: BLE001
        _save_history(history)
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    assistant_msg = {"role": "assistant", "text": reply, "ts": time.time()}
    history.append(assistant_msg)
    _save_history(history)
    return assistant_msg
