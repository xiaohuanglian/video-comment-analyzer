"""本地模型连接与只读通道状态。"""
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/system-status")
def system_status() -> dict:
    from api.services.system_status import snapshot
    return snapshot()

class ModelSettingsRequest(BaseModel):
    base_url: str = ""
    model_name: str = ""
    api_key: str = ""  # 空 = 保留原有 key


@router.get("/model")
def get_model_settings() -> Dict[str, Any]:
    from ..services import model_settings

    return model_settings.masked_view()


@router.post("/model")
def post_model_settings(body: ModelSettingsRequest) -> Dict[str, Any]:
    from ..services import model_settings

    stored = model_settings.load_model_settings()
    api_key = body.api_key.strip() or stored.get("api_key", "")
    payload = model_settings.save_model_settings(
        body.base_url or stored.get("base_url", ""),
        body.model_name or stored.get("model_name", ""),
        api_key,
    )
    return model_settings.masked_view(payload)


@router.delete("/model")
def delete_model_settings() -> Dict[str, Any]:
    from ..services import model_settings

    model_settings.clear_model_settings()
    return {"ok": True}


@router.post("/model/test")
def post_model_settings_test(body: Optional[ModelSettingsRequest] = None) -> Dict[str, Any]:
    """服务端连接测试：避免浏览器跨域；也顺带验证 function calling 兼容。"""
    from ..services import model_settings
    from ..services.insight.llm_analyzer import build_openai_client

    creds = model_settings.resolve_credentials(
        (body.api_key if body else "") or "",
        (body.base_url if body else "") or "",
        (body.model_name if body else "") or "",
    )
    if not creds["api_key"]:
        return {"ok": False, "error": "未配置 API Key"}
    client = build_openai_client(creds["base_url"] or "https://api.deepseek.com", creds["api_key"], feature="settings")
    import time as _t

    t0 = _t.monotonic()
    try:
        completion = client.chat.completions.create(
            model=creds["model_name"] or "deepseek-v4-flash",
            messages=[{"role": "user", "content": "回复 ok"}],
            max_tokens=8,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=30,
        )
        content = completion.choices[0].message.content or ""
        return {"ok": True, "latency_s": round(_t.monotonic() - t0, 1),
                "model_reply": content[:30], "base_url": creds["base_url"],
                "note": "function calling 兼容性会在首次真实任务时最终确认"}
    except Exception as exc:
        return {"ok": False, "error": f"模型连接失败（{type(exc).__name__}），请检查网关、凭据及网络"}
