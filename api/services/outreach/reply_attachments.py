"""人工添加的回复图片：本地保存，只有批准发送时才上传平台。"""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[3] / 'data' / 'automation' / 'reply_attachments'
MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 3
FORMATS = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'), 'GIF': ('gif', 'image/gif')}


def inspect_image(content: bytes, original_name: str = '') -> dict[str, Any]:
    if not content or len(content) > MAX_BYTES:
        raise ValueError('图片不能为空，单张最多 8MB')
    try:
        with Image.open(io.BytesIO(content)) as picture:
            if picture.format not in FORMATS:
                raise ValueError('只支持 PNG、JPEG、GIF 图片')
            if picture.width * picture.height > 20_000_000:
                raise ValueError('图片像素过大，请使用不超过2000万像素的图片')
            extension, mime = FORMATS[picture.format]
            width, height = picture.size
            picture.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('图片内容损坏或不是支持的图片格式') from exc
    return {'attachment_id': hashlib.sha256(content).hexdigest(), 'extension': extension,
            'mime_type': mime, 'size': len(content), 'width': width, 'height': height,
            'original_name': re.sub(r'[^\w.\-\u4e00-\u9fff ]', '_', Path(original_name).name)[:100] or f'图片.{extension}'}


def image_path(metadata: dict[str, Any]) -> Path:
    identity = str(metadata.get('attachment_id') or '')
    extension = str(metadata.get('extension') or '')
    if not re.fullmatch(r'[a-f0-9]{64}', identity) or extension not in {v[0] for v in FORMATS.values()}:
        raise ValueError('图片附件标识无效')
    path = ROOT / f'{identity}.{extension}'
    if path.resolve().parent != ROOT.resolve():
        raise ValueError('图片附件路径无效')
    return path


def store_image(content: bytes, metadata: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    path = image_path(metadata)
    if path.exists():
        return
    # 二进制文件原子落盘；元数据由 AutomationStore 的 JSON 锁与原子写保存。
    fd, temporary = tempfile.mkstemp(dir=ROOT, prefix='.upload-')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_image(metadata: dict[str, Any]) -> bytes:
    try:
        content = image_path(metadata).read_bytes()
    except OSError as exc:
        raise ValueError("图片附件不存在或无法读取，请重新添加并审核") from exc
    if hashlib.sha256(content).hexdigest() != metadata.get('attachment_id'):
        raise ValueError('图片附件已改变，请重新审核')
    return content


def supports_images(platform: str) -> bool:
    return platform in ('bili', 'bilibili')
