# -*- coding: utf-8 -*-
"""把 model_settings.json 的 base_url 归一成根地址（去掉结尾 /v1）。

背景（2026-11-11）：旧版 `normalize_base_url()` 会给 base URL **补 `/v1`**
并以此持久化，而 `llm.py` 又自己拼 `/v1/chat/completions`，两者叠加会请求
`.../v1/v1/chat/completions`。

读取侧已经统一归一（`llm_config.resolve_llm_config`），所以**不迁移也能正常用**；
但磁盘上留着旧格式很容易让人以为配置本身是对的，下次有人手写新代码
再拼一次 `/v1` 就复发了。这个脚本把存量文件就地改成根地址。

幂等、可重复执行。

用法：
    uv run python -m scripts.migrate_model_settings --dry-run
    uv run python -m scripts.migrate_model_settings
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "data" / "model_settings.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="归一 model_settings.json 的 base_url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", default=str(SETTINGS))
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"没有配置文件：{path}（未配置模型，跳过）")
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"配置文件无法解析，未改动：{exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("配置格式异常（不是对象），未改动", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT))
    from api.services.llm_config import normalize_base_url

    old = str(data.get("base_url") or "")
    new = normalize_base_url(old)
    if old == new:
        print(f"已是根地址，无需改动：{old}")
        return 0

    print(f"base_url：{old}  →  {new}")
    if args.dry_run:
        print("（dry-run，未写入）")
        return 0

    data["base_url"] = new
    tmp = path.with_suffix(".migrating")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"已写入：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
