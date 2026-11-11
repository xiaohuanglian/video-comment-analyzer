"""词频与词云生成。

性能约束（2026-11-11 审计）：本模块原先在**模块级** import
`matplotlib.pyplot` / `wordcloud` / `jieba`。它被
`tools/async_file_writer.py` → `store/bilibili/_store_impl.py` →
`media_platform/bilibili/core.py` → `api.services.creator_rank` →
`api/routers/bilibili.py` → `api.main` 一路串起来，结果是 **Web 服务启动
时有 18 秒花在给词云加载绘图库上**（实测 `import api.main` 22 秒）。

现在三个重包都改成**函数内导入**：只有真的要画词云时才付这笔钱。
`tools/async_file_writer.py` 只用到 `AsyncWordCloudGenerator` 这个类，
构造它也不再触发 matplotib 导入。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from typing import Any

import aiofiles

import config
from tools import utils

plot_lock = asyncio.Lock()


def _jieba():
    """延迟导入结巴（首次分词的初始化开销只在真正用到时付）。"""
    import jieba

    return jieba


class AsyncWordCloudGenerator:
    def __init__(self):
        logging.getLogger("jieba").setLevel(logging.WARNING)
        self.stop_words_file = config.STOP_WORDS_FILE
        self.lock = asyncio.Lock()
        self.stop_words = self.load_stop_words()
        self.custom_words = config.CUSTOM_WORDS
        self._jieba_ready = False

    def _ensure_custom_words(self) -> Any:
        jieba = _jieba()
        if not self._jieba_ready:
            for word in self.custom_words:
                jieba.add_word(word)
            self._jieba_ready = True
        return jieba

    def load_stop_words(self):
        # docs/ 下的停用词/字体文件是可选资源（不在版本库中）；缺失时降级而不是崩溃。
        try:
            with open(self.stop_words_file, "r", encoding="utf-8") as f:
                return set(f.read().strip().split("\n"))
        except (FileNotFoundError, OSError):
            utils.logger.warning(
                f"[words] 停用词文件不存在：{self.stop_words_file}，改用空停用词表（词云功能仍可用）"
            )
            return set()

    async def generate_word_frequency_and_cloud(self, data, save_words_prefix):
        jieba = self._ensure_custom_words()
        all_text = " ".join(item["content"] for item in data)
        words = [
            word
            for word in jieba.lcut(all_text)
            if word not in self.stop_words and len(word.strip()) > 0
        ]
        word_freq = Counter(words)

        # Save word frequency to file
        freq_file = f"{save_words_prefix}_word_freq.json"
        async with aiofiles.open(freq_file, "w", encoding="utf-8") as file:
            await file.write(json.dumps(word_freq, ensure_ascii=False, indent=4))

        # Try to acquire the plot lock without waiting
        if plot_lock.locked():
            utils.logger.info("Skipping word cloud generation as the lock is held.")
            return

        await self.generate_word_cloud(word_freq, save_words_prefix)

    async def generate_word_cloud(self, word_freq, save_words_prefix):
        font_path = config.FONT_PATH
        if font_path and not os.path.exists(font_path):
            utils.logger.warning(
                f"[words] 中文字体文件不存在：{font_path}，跳过词云图片生成"
                f"（词频 JSON 已生成；如需词云请将中文字体放到该路径）"
            )
            return
        await plot_lock.acquire()
        try:
            # 重包延迟到真正要画图时再导入（见模块 docstring）。
            import matplotlib

            matplotlib.use("Agg")  # 无 GUI 环境必须用非交互后端
            import matplotlib.pyplot as plt
            from wordcloud import WordCloud

            top_20_word_freq = {
                word: freq
                for word, freq in sorted(word_freq.items(), key=lambda item: item[1], reverse=True)[:20]
            }
            wordcloud = WordCloud(
                font_path=font_path or None,
                width=800,
                height=400,
                background_color="white",
                max_words=200,
                stopwords=self.stop_words,
                colormap="viridis",
                contour_color="steelblue",
                contour_width=1,
            ).generate_from_frequencies(top_20_word_freq)

            # Save word cloud image
            plt.figure(figsize=(10, 5), facecolor="white")
            plt.imshow(wordcloud, interpolation="bilinear")

            plt.axis("off")
            plt.tight_layout(pad=0)
            plt.savefig(f"{save_words_prefix}_word_cloud.png", format="png", dpi=300)
            plt.close()
        finally:
            plot_lock.release()
