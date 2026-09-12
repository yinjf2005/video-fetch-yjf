#!/usr/bin/env python3
"""Layer 4.3: sync Markdown notes to ima knowledge base via OpenAPI.

Auth uses two custom headers (NOT the standard Authorization header):
  X-IMA-Client-Id / X-IMA-Api-Key
See references/ima-openapi.md for details.
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List


def _headers(cfg: Dict) -> Dict[str, str]:
    client_id = os.environ.get("IMA_CLIENT_ID") or (cfg.get("knowledge_base", {}).get("ima", {}).get("client_id", ""))
    api_key = os.environ.get("IMA_API_KEY") or (cfg.get("knowledge_base", {}).get("ima", {}).get("api_key", ""))
    if not client_id or not api_key:
        raise RuntimeError("ERR_SYNC_IMA: 缺少 IMA_CLIENT_ID / IMA_API_KEY")
    return {"X-IMA-Client-Id": client_id, "X-IMA-Api-Key": api_key, "Content-Type": "application/json"}


def upload_file(path: str | Path, cfg: Dict, target_kb: str = "default", retries: int = 3) -> bool:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("ERR_SYNC_IMA: 文件不存在或为空")
    headers = _headers(cfg)
    url = "https://ima.qq.com/openapi/v1/knowledge/upload"  # 示例端点，以官方文档为准
    body = json.dumps({"target_kb": target_kb, "filename": path.name}).encode("utf-8")

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0 or data.get("success"):
                print(f"[OK] ima 同步成功：{path.name}")
                return True
            last_err = str(data)
        except (urllib.error.URLError, ValueError) as e:
            last_err = str(e)
        print(f"[WARN] ima 同步第 {attempt} 次失败：{last_err}")
    raise RuntimeError(f"ERR_SYNC_IMA: 重试 {retries} 次仍失败：{last_err}")


def upload_dir(directory: str | Path, cfg: Dict) -> List[str]:
    directory = Path(directory)
    failed = []
    for md in sorted(directory.glob("*.md")):
        try:
            upload_file(md, cfg)
        except RuntimeError as e:
            failed.append(str(e))
    return failed


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: sync_ima.py <file_or_dir> [config.yaml]")
        return 2
    import common

    cfg = common.load_config(sys.argv[2]) if len(sys.argv) > 2 else common.load_config()
    p = Path(sys.argv[1])
    if p.is_dir():
        failed = upload_dir(p, cfg)
        return 1 if failed else 0
    try:
        upload_file(p, cfg)
        return 0
    except RuntimeError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
