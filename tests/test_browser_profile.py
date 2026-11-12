"""浏览器档案分离：采集档不能污染发送档。

为什么重要
----------
2026-11-11 小红书账号被风控后，连带失去的是**发评论 / 发笔记**能力——因为采集与发送
共用同一个浏览器档案（同一个账号）。文档写着「切勿使用主号采集」，代码里却把档案目录
写死在 8 个地方，谁也改不动。这里把那 8 处收成一个函数，并锁住「采集档与主档不同」。
"""
import os

import pytest

import config
from tools import browser_profile as bp


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """每个用例后恢复配置，避免污染其它测试。"""
    yield


def _set(monkeypatch, suffix: str, port: int = 0):
    monkeypatch.setattr(config, "CRAWL_PROFILE_SUFFIX", suffix, raising=False)
    monkeypatch.setattr(config, "CRAWL_DEBUG_PORT", port, raising=False)


class TestProfileDir:
    def test_default_is_main_profile(self, monkeypatch):
        _set(monkeypatch, "")
        path = bp.resolve_user_data_dir("xhs")
        assert path is not None
        assert path.endswith(os.path.join("browser_data", "cdp_xhs_user_data_dir"))
        assert not path.endswith("_collect")

    def test_collect_profile_is_a_different_directory(self, monkeypatch):
        _set(monkeypatch, "")
        main = bp.resolve_user_data_dir("xhs")
        _set(monkeypatch, "_collect")
        collect = bp.resolve_user_data_dir("xhs")
        assert main != collect
        assert collect.endswith("cdp_xhs_user_data_dir_collect")

    def test_collect_profile_is_created(self, monkeypatch):
        _set(monkeypatch, "_collect")
        path = bp.resolve_user_data_dir("xhs")
        assert os.path.isdir(path)

    def test_platform_defaults_to_config(self, monkeypatch):
        _set(monkeypatch, "_collect")
        monkeypatch.setattr(config, "PLATFORM", "xhs")
        assert "xhs" in bp.resolve_user_data_dir()

    def test_save_login_state_off_returns_none(self, monkeypatch):
        _set(monkeypatch, "_collect")
        monkeypatch.setattr(config, "SAVE_LOGIN_STATE", False)
        assert bp.resolve_user_data_dir("xhs") is None

    def test_whitespace_suffix_is_ignored(self, monkeypatch):
        _set(monkeypatch, "   ")
        assert bp.profile_suffix() == ""
        assert bp.using_separate_profile() is False


class TestDebugPort:
    def test_default_falls_back_to_cdp_port(self, monkeypatch):
        _set(monkeypatch, "", 0)
        monkeypatch.setattr(config, "CDP_DEBUG_PORT", 9222)
        assert bp.crawl_debug_port() == 9222

    def test_collect_port_wins(self, monkeypatch):
        _set(monkeypatch, "_collect", 9223)
        monkeypatch.setattr(config, "CDP_DEBUG_PORT", 9222)
        assert bp.crawl_debug_port() == 9223

    def test_garbage_port_falls_back(self, monkeypatch):
        monkeypatch.setattr(config, "CRAWL_DEBUG_PORT", "abc", raising=False)
        monkeypatch.setattr(config, "CDP_DEBUG_PORT", 9333)
        assert bp.crawl_debug_port() == 9333


class TestProfileEnv:
    def test_no_env_when_disabled(self, monkeypatch):
        _set(monkeypatch, "")
        assert bp.crawl_profile_env() == {}

    def test_env_carries_suffix_and_port(self, monkeypatch):
        _set(monkeypatch, "_collect", 9223)
        env = bp.crawl_profile_env()
        assert env["CRAWL_PROFILE_SUFFIX"] == "_collect"
        assert env["CRAWL_DEBUG_PORT"] == "9223"

    def test_env_omits_zero_port(self, monkeypatch):
        _set(monkeypatch, "_collect", 0)
        assert "CRAWL_DEBUG_PORT" not in bp.crawl_profile_env()


class TestNoHardcodedProfileDirs:
    """防回归：平台 core 里不许再出现自己拼 browser_data 的代码。"""

    PLATFORMS = ("xhs", "bilibili", "douyin", "weibo", "tieba", "kuaishou", "zhihu")

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_platform_uses_shared_helper(self, platform):
        import inspect

        mod = __import__(f"media_platform.{platform}.core", fromlist=["core"])
        src = inspect.getsource(mod)
        assert "browser_profile.resolve_user_data_dir()" in src
        # 旧写法：自己 os.path.join("browser_data", ...)
        assert "config.USER_DATA_DIR % config.PLATFORM" not in src


class TestCollectEnvDoesNotBorrowCookies:
    def test_separate_profile_drops_sender_cookie(self, monkeypatch):
        """启用采集档时必须丢掉从发送侧抓来的 Cookie——那正是读侧拖垮写侧的路径。"""
        from api.services.outreach import reply_automation as auto

        _set(monkeypatch, "_collect", 9223)
        env = auto._collect_env("xhs", "SESSDATA=from_sender_side")
        assert env["CDP_CONNECT_EXISTING"] == "0"
        assert "VC_CRAWLER_COOKIES" not in env
        assert env["CRAWL_PROFILE_SUFFIX"] == "_collect"

    def test_default_profile_keeps_old_behavior(self, monkeypatch):
        from api.services.outreach import reply_automation as auto

        _set(monkeypatch, "")
        env = auto._collect_env("xhs", "SESSDATA=x")
        assert env["CDP_CONNECT_EXISTING"] == "1"
        assert env["VC_CRAWLER_COOKIES"] == "SESSDATA=x"

    def test_bili_still_launches_its_own_browser(self, monkeypatch):
        from api.services.outreach import reply_automation as auto

        _set(monkeypatch, "")
        assert auto._collect_env("bili")["CDP_CONNECT_EXISTING"] == "0"
