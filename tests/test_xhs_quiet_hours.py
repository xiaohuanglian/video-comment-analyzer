"""夜间静默：采集不该在凌晨三点开工。

依据（2026-11-11 事故后补）：12 个搜索词挤在 40 秒内是主因，但「什么时候搜」同样是信号。
真人不会凌晨三点爬起来搜六个不相关的话题；发送侧早就有 09:00–22:00 窗口，采集侧此前
完全没有作息概念。
"""
from datetime import datetime

import pytest

import config
from tools import xhs_safety as xs


def _ts(hour: int, minute: int = 0) -> float:
    """今天的某个时刻（本地时间）的时间戳。"""
    now = datetime.now()
    return datetime(now.year, now.month, now.day, hour, minute).timestamp()


@pytest.fixture(autouse=True)
def _isolated_budget(tmp_path):
    xs.reset_search_budget(xs.SearchBudget(tmp_path / "budget.json"))
    yield
    xs.reset_search_budget(None)


class TestQuietHours:
    def test_default_window(self):
        assert xs.quiet_hours() == (1, 6)

    @pytest.mark.parametrize("hour,expected", [(0, False), (1, True), (3, True), (5, True), (6, False), (14, False)])
    def test_inside_and_outside(self, hour, expected):
        assert xs.in_quiet_hours(_ts(hour)) is expected

    def test_window_is_half_open(self):
        """24:00 结束（06:00 整）算白天，05:59 还算夜里。"""
        assert xs.in_quiet_hours(_ts(5, 59)) is True
        assert xs.in_quiet_hours(_ts(6, 0)) is False

    def test_cross_midnight_window(self, monkeypatch):
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_START", 23, raising=False)
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_END", 5, raising=False)
        assert xs.in_quiet_hours(_ts(23, 30)) is True
        assert xs.in_quiet_hours(_ts(2)) is True
        assert xs.in_quiet_hours(_ts(12)) is False

    def test_start_equals_end_disables(self, monkeypatch):
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_START", 0, raising=False)
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_END", 0, raising=False)
        assert xs.in_quiet_hours(_ts(3)) is False

    def test_hours_are_wrapped_to_day(self, monkeypatch):
        """配了 25 也要当 1 点处理，别抛异常。"""
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_START", 25, raising=False)
        monkeypatch.setattr(config, "XHS_QUIET_HOURS_END", 30, raising=False)
        assert xs.quiet_hours() == (1, 6)


class TestSecondsUntilEnd:
    def test_returns_positive_within_window(self):
        wait = xs.seconds_until_quiet_end(_ts(3))
        assert 2.9 * 3600 < wait <= 3.1 * 3600

    def test_rolls_to_next_day_when_past_end(self):
        """白天问「还有多久结束」要说的是明天早上，而不是负数。"""
        wait = xs.seconds_until_quiet_end(_ts(14))
        assert wait > 0

    def test_format_seconds(self):
        assert xs.format_seconds(11520) == "3 小时 12 分"
        assert xs.format_seconds(3661) == "1 小时 1 分"
        assert xs.format_seconds(59) == "59 秒"


class TestEnsureNotQuietHours:
    def test_raises_during_window(self):
        with pytest.raises(xs.QuietHoursActive) as exc:
            xs.ensure_not_quiet_hours(_ts(3))
        assert "夜间静默" in str(exc.value)
        assert exc.value.retry_after_seconds > 0

    def test_passes_during_day(self):
        xs.ensure_not_quiet_hours(_ts(14))

    def test_is_a_search_budget_error(self):
        """上层统一 except SearchBudgetExceeded 就能接住，不用另写一条分支。"""
        assert issubclass(xs.QuietHoursActive, xs.SearchBudgetExceeded)


class TestEntriesAreWired:
    """防回归：三个入口都必须真的调用它。"""

    def test_main_py_checks_before_start(self):
        import inspect

        import main

        src = inspect.getsource(main)
        assert "ensure_not_quiet_hours" in src

    def test_xhs_crawler_search_checks(self):
        import inspect

        from media_platform.xhs import core

        src = inspect.getsource(core.XiaoHongShuCrawler.search)
        assert "ensure_not_quiet_hours" in src

    def test_keyword_script_checks(self):
        import inspect

        from scripts import xhs_keyword_notes

        src = inspect.getsource(xhs_keyword_notes.collect)
        assert "ensure_not_quiet_hours" in src
