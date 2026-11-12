"""浏览器档案（user data dir）与调试端口的唯一解析入口。

为什么要有这个模块
------------------
2026-11-11 小红书账号被风控的真实代价，不只是「采集中断」，而是**采集与发送共用同一个
浏览器档案**：读侧（采集）撞一次验证码，写侧（发评论 / 发笔记）跟着一起废掉。文档里那句
「切勿使用主号采集」我们一直没做到——技术原因是档案目录写死在 8 个地方：

    os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)

一处改不动就全部失效，所以没有人去改。这里把它收成一个函数，8 处全部调用它。

两种运行身份
------------
- **主档（默认）**：`browser_data/cdp_xhs_user_data_dir`，端口 `CDP_DEBUG_PORT`（9222）。
  发送侧（`api/services/outreach/*`）连的就是这个——它连的是「哪个浏览器开着调试端口」，
  不是「哪个目录」，所以主档必须保持端口不变。
- **采集档（可选）**：`browser_data/cdp_xhs_collect_user_data_dir`，端口
  `CRAWL_DEBUG_PORT`（默认 9223）。由 `CRAWL_PROFILE_SUFFIX` 环境变量开启。

为什么不默认开启
----------------
分离只有在**另有一个账号**时才有意义。如果两个档案登的是同一个账号，只是把这一个账号
变成两台「设备」，反而更像异常登录。所以默认关闭，由使用者显式开启：

    CRAWL_PROFILE_SUFFIX=_collect CRAWL_DEBUG_PORT=9223 ./run_web.sh

开启后采集子进程会用自己的档案与端口，`kill_stale_browsers` 也只清采集档，不会再把正在
登录/发送的主档浏览器当残留杀掉（这是 `reply_automation._collect_env` 当初必须让 xhs
`CDP_CONNECT_EXISTING=1` 的原因）。
"""
import os
from typing import Optional

import config


def profile_suffix() -> str:
    """采集档后缀；空串表示用主档。"""
    return str(getattr(config, "CRAWL_PROFILE_SUFFIX", "") or "").strip()


def using_separate_profile() -> bool:
    return bool(profile_suffix())


def resolve_user_data_dir(platform: Optional[str] = None) -> Optional[str]:
    """当前进程该用的浏览器档案目录。

    `SAVE_LOGIN_STATE` 关闭时返回 None（不持久化登录态，走无痕 context）。
    """
    if not getattr(config, "SAVE_LOGIN_STATE", True):
        return None
    name = platform or config.PLATFORM
    suffix = profile_suffix()
    dir_name = f"cdp_{config.USER_DATA_DIR % name}{suffix}"
    path = os.path.join(os.getcwd(), "browser_data", dir_name)
    os.makedirs(path, exist_ok=True)
    return path


def crawl_debug_port() -> int:
    """当前进程该用的 CDP 调试端口。

    `CRAWL_DEBUG_PORT` 为 0/未设时回落 `CDP_DEBUG_PORT`（发送侧固定用后者）。
    """
    raw = getattr(config, "CRAWL_DEBUG_PORT", 0) or 0
    try:
        port = int(raw)
    except (TypeError, ValueError):
        port = 0
    if port > 0:
        return port
    try:
        return int(getattr(config, "CDP_DEBUG_PORT", 9222) or 9222)
    except (TypeError, ValueError):
        return 9222


def crawl_profile_env() -> dict:
    """给采集子进程注入的采集档环境变量；未启用时返回空 dict。

    子进程是独立 Python 进程，`config` 会重新导入——所以这里显式把值写进 env，
    而不是指望它在磁盘配置里也有。
    """
    suffix = profile_suffix()
    if not suffix:
        return {}
    env = {"CRAWL_PROFILE_SUFFIX": suffix}
    try:
        port = int(getattr(config, "CRAWL_DEBUG_PORT", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    if port > 0:
        env["CRAWL_DEBUG_PORT"] = str(port)
    return env
