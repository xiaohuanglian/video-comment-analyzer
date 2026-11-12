# Xiaohongshu signature generation using xhshow pure-algorithm library
#
# 致谢：本签名实现依赖 xhshow 开源库, 由 Cloxl 提供
# 仓库地址: https://github.com/Cloxl/xhshow
# 许可协议: MIT License
#
# 依赖 xhshow>=0.2.0：该版本原生修好了 GET 请求 a3_hash 的计算
# (https://github.com/Cloxl/xhshow/issues/104)，并把上报给平台的 SDK 版本
# 从 4.2.6 提到 4.3.5。旧版我们在这里 monkey-patch `build_payload_array`，
# 0.2.0 改了函数签名（多了 hex_md5_path 参数），patch 会直接 TypeError，
# 所以升级时把 patch 一起删掉——不是绕过问题，是问题在库里已经修了。

import hashlib
import json
import time
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

from .xhs_sign import get_trace_id


def _build_sign_string(uri: str, data: Optional[Union[Dict, str]] = None, method: str = "POST") -> str:
    """Build content string to be signed

    Args:
        uri: API path
        data: Request data
        method: Request method (GET or POST)

    Returns:
        Content string for signing
    """
    if method.upper() == "POST":
        c = uri
        if data is not None:
            if isinstance(data, dict):
                c += json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            elif isinstance(data, str):
                c += data
        return c
    else:
        if not data or (isinstance(data, dict) and len(data) == 0):
            return uri
        if isinstance(data, dict):
            params = []
            for key in data.keys():
                value = data[key]
                if isinstance(value, list):
                    value_str = ",".join(str(v) for v in value)
                elif value is not None:
                    value_str = str(value)
                else:
                    value_str = ""
                # URL encoding: preserve commas to match browser behavior
                value_str = quote(value_str, safe=',')
                params.append(f"{key}={value_str}")
            return f"{uri}?{'&'.join(params)}"
        elif isinstance(data, str):
            return f"{uri}?{data}"
        return uri


def sign_with_xhshow(
    uri: str,
    data: Optional[Union[Dict, str]] = None,
    cookie_str: str = "",
    method: str = "POST",
    *,
    x_rap: bool = False,
) -> Dict[str, Any]:
    """
    使用 xhshow 纯算法生成完整签名请求头

    Args:
        uri: API path
        data: Request data (GET params dict or POST payload dict)
        cookie_str: Cookie string
        method: Request method (GET or POST)
        x_rap: 是否额外生成 x-rap-param。xhshow 0.2.0 起，feed / search /
            发布类接口的浏览器请求会带这个头，缺失本身就是个可观测的差异。

    Returns:
        Dictionary containing x-s, x-t, x-s-common, x-b3-traceid
    """
    from xhshow import Xhshow

    xhshow_client = Xhshow()
    payload = data if isinstance(data, dict) else {}

    if method.upper() == "POST":
        headers = xhshow_client.sign_headers_post(
            uri=uri,
            cookies=cookie_str,
            payload=payload,
            x_rap=x_rap,
        )
    else:
        headers = xhshow_client.sign_headers_get(
            uri=uri,
            cookies=cookie_str,
            params=payload,
            x_rap=x_rap,
        )

    out = {
        "x-s": headers.get("x-s", ""),
        "x-t": headers.get("x-t", ""),
        "x-s-common": headers.get("x-s-common", ""),
        "x-b3-traceid": headers.get("x-b3-traceid", get_trace_id()),
    }
    # 0.2.0 新增的头，有就透传，没有不影响老调用方
    for key in ("x-xray-traceid", "x-mns", "xy-direction", "x-rap-param"):
        if headers.get(key):
            out[key] = headers[key]
    return out
