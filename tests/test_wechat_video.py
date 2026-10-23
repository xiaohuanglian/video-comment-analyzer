# -*- coding: utf-8 -*-
"""公众号文章视频下载:嵌入提取与播放地址解析(纯离线单元测试)。"""

from __future__ import annotations

import base64

from bs4 import BeautifulSoup

from api.services import wechat_native as wn


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------- _vid_from_url


def test_vid_from_url_qq_iframe():
    url = "https://v.qq.com/iframe/preview.html?width=500&height=375&auto=0&vid=v0512abc123"
    assert wn._vid_from_url(url) == "v0512abc123"


def test_vid_from_url_readtemplate_wxv():
    url = "https://mp.weixin.qq.com/mp/readtemplate?t=pages/video_list_tmpl&vid=wxv_abc&autoplay=0"
    assert wn._vid_from_url(url) == "wxv_abc"


def test_vid_from_url_no_vid():
    assert wn._vid_from_url("https://example.com/x?foo=1") == ""


# ------------------------------------------------------------ _extract_video_embeds


def test_extract_embeds_iframe_and_mpvideo_with_dedup():
    html = """
    <div id="js_content">
      <p>开头</p>
      <iframe class="video_iframe" data-src="https://v.qq.com/iframe/preview.html?vid=v0512xyz"></iframe>
      <mp-common-mpvideo data-mpvid="wxv_111" data-src="/mp/readtemplate?t=pages/video_list_tmpl&vid=wxv_111"></mp-common-mpvideo>
      <iframe class="video_iframe" data-src="https://v.qq.com/iframe/preview.html?vid=v0512xyz"></iframe>
      <iframe class="video_iframe" data-src="https://v.qq.com/iframe/preview.html?vid=u0999dup"></iframe>
      <p>结尾</p>
    </div>
    """
    embeds = wn._extract_video_embeds(_soup(html).find(id="js_content"))
    vids = [e["vid"] for e in embeds]
    # 同 vid 去重,不同 vid 保序保留
    assert vids == ["v0512xyz", "wxv_111", "u0999dup"]
    assert all(not e["src"] for e in embeds)


def test_extract_embeds_native_mpvideo_reads_mpvid():
    html = '<div><mp-common-mpvideo data-mpvid="wxv_native01"></mp-common-mpvideo></div>'
    embeds = wn._extract_video_embeds(_soup(html).find("div"))
    assert embeds and embeds[0]["vid"] == "wxv_native01"


def test_extract_embeds_bare_video_tag_direct_src():
    html = '<div><video data-src="https://example.com/a.mp4"></video><video src="https://example.com/b.mp4"></video></div>'
    embeds = wn._extract_video_embeds(_soup(html).find("div"))
    srcs = [e["src"] for e in embeds]
    assert srcs == ["https://example.com/a.mp4", "https://example.com/b.mp4"]


def test_extract_embeds_ignores_non_video_iframe():
    html = '<div><iframe class="video_iframe" data-src="https://example.com/no-vid"></iframe></div>'
    assert wn._extract_video_embeds(_soup(html).find("div")) == []


# ---------------------------------------------------------------- _parse_getinfo


def test_parse_getinfo_success():
    text = 'QZOutputJson={"errcode":0,"vl":{"vi":[{"fn":"v0512xyz.mp4","fvkey":"KEY123","ul":{"ui":[{"url":"https://cdn.example.com/path"}]}}]}};'
    info = wn._parse_getinfo(text)
    assert info is not None
    vi = info["vl"]["vi"][0]
    assert vi["fn"] == "v0512xyz.mp4"
    assert vi["fvkey"] == "KEY123"
    assert vi["ul"]["ui"][0]["url"] == "https://cdn.example.com/path"


def test_parse_getinfo_error_code_returns_none():
    text = 'QZOutputJson={"errcode":104,"msg":"vid not exist"};'
    assert wn._parse_getinfo(text) is None


def test_parse_getinfo_garbage_returns_none():
    assert wn._parse_getinfo("<html>bad</html>") is None


# ---------------------------------------------------------------- _pick_wxv_url


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_pick_wxv_url_prefers_highest_resolution():
    lo, hi = "https://cdn.example.com/lo.mp4", "https://cdn.example.com/hi.mp4"
    text = (
        'window.video_list = {"list_1":{"vid_width":640,"vid_height":360,"encode_id":"m1205","main_url":"'
        + _b64(lo)
        + '"},"list_2":{"vid_width":1920,"vid_height":1080,"encode_id":"m1305","main_url":"'
        + _b64(hi)
        + '"}};'
    )
    assert wn._pick_wxv_url(text) == hi


def test_pick_wxv_url_pure_json():
    url = "https://cdn.example.com/only.mp4"
    text = '{"video_list":{"list_1":{"vid_width":1280,"vid_height":720,"main_url":"' + _b64(url) + '"}}}'
    assert wn._pick_wxv_url(text) == url


def test_pick_wxv_url_regex_fallback():
    url = "https://cdn.example.com/fallback.mp4"
    # 无法整体 json 解析的响应里,直接抓 main_url(取最后一个)
    text = 'garbage prefix "main_url":"' + _b64(url) + '" garbage suffix'
    assert wn._pick_wxv_url(text) == url


def test_pick_wxv_url_nothing_found():
    assert wn._pick_wxv_url("window.video_list = {};") == ""


# ---------------------------------------------------------------- _b64decode


def test_b64decode_unpadded():
    url = "https://cdn.example.com/x.mp4?a=1"
    assert wn._b64decode(_b64(url).rstrip("=")) == url


def test_b64decode_invalid_returns_empty():
    assert wn._b64decode("!!!not-base64!!!") == ""
