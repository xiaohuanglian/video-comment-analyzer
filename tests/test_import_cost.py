# -*- coding: utf-8 -*-
"""启动开销门禁：导入 Web 应用不应把绘图库一并拖进来。

背景（2026-11-11 审计）：`api.main` 导入耗时 22 秒，其中 18 秒来自
`tools/words.py` 在模块级 import `matplotlib.pyplot`，经
async_file_writer → store.bilibili → media_platform.bilibili → creator_rank
→ routers.bilibili 一路串到 app 启动。改成函数内延迟导入后降到约 3 秒。

这个测试用**子进程**验证，避免受当前进程已加载模块的影响。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_importing_web_app_does_not_pull_matplotlib():
    result = _run(
        """
        import sys
        import api.main  # noqa: F401
        heavy = [m for m in ("matplotlib", "matplotlib.pyplot", "wordcloud") if m in sys.modules]
        print(",".join(heavy))
        """
    )
    assert result.returncode == 0, result.stderr
    loaded = result.stdout.strip()
    assert loaded == "", f"Web 启动不应导入绘图库，实际加载了：{loaded}"


def test_importing_words_module_is_cheap():
    result = _run(
        """
        import sys
        import tools.words  # noqa: F401
        heavy = [m for m in ("matplotlib", "matplotlib.pyplot", "wordcloud", "jieba") if m in sys.modules]
        print(",".join(heavy))
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "tools.words 导入时不应拉起重包"


def test_word_cloud_generator_can_be_constructed_without_matplotlib():
    result = _run(
        """
        import sys
        from tools.words import AsyncWordCloudGenerator
        AsyncWordCloudGenerator()
        print("matplotlib" in sys.modules, "wordcloud" in sys.modules)
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_app_import_stays_under_budget():
    """宽松上限：只要没人再把绘图库塞回 import 链，就不可能接近它。

    用 **CPU 时间**而不是墙钟：这台机器上跑测试时负载能到 35+，同一份代码
    墙钟在 3s 和 23s 之间跳（实测），拿墙钟当门禁必然误报。CPU 时间 1.8s
    左右且稳定；真把 matplotlib 塞回 import 链，CPU 会明显上去。
    墙钟仍然打印出来，方便看趋势。
    """
    result = _run(
        """
        import time
        w = time.time()
        c = time.process_time()
        import api.main  # noqa: F401
        print(f"{time.process_time() - c:.2f} {time.time() - w:.2f}")
        """
    )
    assert result.returncode == 0, result.stderr
    cpu_text, wall_text = result.stdout.split()
    cpu, wall = float(cpu_text), float(wall_text)
    assert cpu < 8, f"api.main 导入 CPU {cpu}s / 墙钟 {wall}s，超出预算（曾因 matplotlib 达 22s）"
