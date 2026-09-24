import asyncio
import json
import logging
import os
from collections import Counter

import aiofiles
import jieba
import matplotlib.pyplot as plt
from wordcloud import WordCloud

import config
from tools import utils

plot_lock = asyncio.Lock()

class AsyncWordCloudGenerator:
    def __init__(self):
        logging.getLogger('jieba').setLevel(logging.WARNING)
        self.stop_words_file = config.STOP_WORDS_FILE
        self.lock = asyncio.Lock()
        self.stop_words = self.load_stop_words()
        self.custom_words = config.CUSTOM_WORDS
        for word, group in self.custom_words.items():
            jieba.add_word(word)

    def load_stop_words(self):
        # docs/ 下的停用词/字体文件是可选资源（不在版本库中）；缺失时降级而不是崩溃。
        try:
            with open(self.stop_words_file, 'r', encoding='utf-8') as f:
                return set(f.read().strip().split('\n'))
        except (FileNotFoundError, OSError):
            utils.logger.warning(
                f"[words] 停用词文件不存在：{self.stop_words_file}，改用空停用词表（词云功能仍可用）"
            )
            return set()

    async def generate_word_frequency_and_cloud(self, data, save_words_prefix):
        all_text = ' '.join(item['content'] for item in data)
        words = [word for word in jieba.lcut(all_text) if word not in self.stop_words and len(word.strip()) > 0]
        word_freq = Counter(words)

        # Save word frequency to file
        freq_file = f"{save_words_prefix}_word_freq.json"
        async with aiofiles.open(freq_file, 'w', encoding='utf-8') as file:
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
            top_20_word_freq = {word: freq for word, freq in
                                sorted(word_freq.items(), key=lambda item: item[1], reverse=True)[:20]}
            wordcloud = WordCloud(
                font_path=font_path or None,
                width=800,
                height=400,
                background_color='white',
                max_words=200,
                stopwords=self.stop_words,
                colormap='viridis',
                contour_color='steelblue',
                contour_width=1
            ).generate_from_frequencies(top_20_word_freq)

            # Save word cloud image
            plt.figure(figsize=(10, 5), facecolor='white')
            plt.imshow(wordcloud, interpolation='bilinear')

            plt.axis('off')
            plt.tight_layout(pad=0)
            plt.savefig(f"{save_words_prefix}_word_cloud.png", format='png', dpi=300)
            plt.close()
        finally:
            plot_lock.release()
