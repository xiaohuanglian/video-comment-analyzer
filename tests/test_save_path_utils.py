# -*- coding: utf-8 -*-

from tools.save_path_utils import (
    build_video_folder_slug,
    join_video_save_path,
    shorten_video_title,
)


def test_shorten_video_title():
    assert shorten_video_title("这是一个很长的视频标题用于测试", max_len=6) == "这是一个很长"
    assert shorten_video_title('含/非法\\字符*?', max_len=20) == "含非法字符"
    assert shorten_video_title("   ", max_len=20) == "video"


def test_build_video_folder_slug():
    slug = build_video_folder_slug("测试视频标题", "BV1vu411e7Fc", max_title_len=4)
    assert slug == "测试视频_BV1vu411e7Fc"


def test_join_video_save_path():
    assert join_video_save_path("./data/comments", "测试_BV1xxx") == "./data/comments/测试_BV1xxx"
