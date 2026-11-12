# -*- coding: utf-8 -*-
"""小红书请求指纹（兼容门面）。

实现已提升到 ``tools/browser_fingerprint.py``——抖音也要用同一份逻辑，
把「从活浏览器读 UA / sec-ch-ua」这件事留在某个平台目录下，另一个平台
就只能复制粘贴，而复制粘贴正是这个模块当初要消灭的东西（三处版本号
互相矛盾就是各写各的造成的）。

这里保留同名导出，老代码与测试的 import 行文不用动。
"""

from tools.browser_fingerprint import (  # noqa: F401
    BrowserFingerprint,
    DeviceProfile,
    derive_from_user_agent,
    fingerprint_mismatches,
    read_browser_fingerprint,
    read_browser_webid,
    read_device_profile,
)

__all__ = [
    "BrowserFingerprint",
    "DeviceProfile",
    "derive_from_user_agent",
    "fingerprint_mismatches",
    "read_browser_fingerprint",
    "read_browser_webid",
    "read_device_profile",
]
