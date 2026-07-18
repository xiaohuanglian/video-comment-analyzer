#!/usr/bin/env bash
# 抓取指定视频/帖子的全量评论（含二级评论，默认安全模式）
#
# 用法:
#   ./fetch_video_comments.sh <平台> <视频链接或ID> [最大评论数]
#
# 平台代码:
#   dy    抖音
#   bili  B站
#   ks    快手
#   xhs   小红书
#   wb    微博
#   zhihu 知乎
#
# 示例:
#   ./fetch_video_comments.sh dy "https://www.douyin.com/video/7525538910311632128"
#   ./fetch_video_comments.sh bili "BV1dwuKzmE26"
#   ./fetch_video_comments.sh dy "7525538910311632128" 5000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ $# -lt 2 ]]; then
  echo "用法: $0 <平台> <视频链接或ID> [最大评论数，默认 10000]"
  echo ""
  echo "平台: dy | bili | ks | xhs | wb | zhihu | tieba"
  exit 1
fi

PLATFORM="$1"
VIDEO_ID="$2"
MAX_COMMENTS="${3:-3000}"
SAFE_MODE="${4:-yes}"
SLEEP_SEC="4"
if [[ "$SAFE_MODE" == "no" || "$SAFE_MODE" == "0" || "$SAFE_MODE" == "false" ]]; then
  SLEEP_SEC="2"
fi

if [[ -f "$HOME/.local/bin/env" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
fi

mkdir -p "./data/comments"

echo "========================================"
echo "  视频评论抓取"
echo "  平台: ${PLATFORM}"
echo "  目标: ${VIDEO_ID}"
echo "  最大评论数: ${MAX_COMMENTS}"
echo "  输出目录: ./data/comments"
echo "========================================"
echo ""
echo "首次运行需扫码登录对应平台，请确保 Chrome 已开启远程调试："
echo "  chrome://inspect/#remote-debugging"
echo ""

uv run main.py \
  --platform "$PLATFORM" \
  --lt qrcode \
  --type detail \
  --specified_id "$VIDEO_ID" \
  --get_comment yes \
  --get_sub_comment no \
  --enable_safe_crawl "$SAFE_MODE" \
  --crawler_max_sleep_sec "$SLEEP_SEC" \
  --max_comments_count_singlenotes "$MAX_COMMENTS" \
  --crawler_max_notes_count 1 \
  --save_data_option jsonl \
  --save_data_path "./data/comments"

echo ""
echo "抓取完成。评论数据保存在 ./data/comments/ 目录下（jsonl 格式）。"
