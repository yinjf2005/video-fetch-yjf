#!/usr/bin/env python3
"""Layer 4.3: sync Markdown notes into an Obsidian Vault (direct filesystem write)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List


def resolve_vault(cfg: Dict) -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT_PATH") or (
        cfg.get("knowledge_base", {}).get("obsidian", {}).get("vault_path", "")
    )
    if not vault:
        raise RuntimeError("ERR_SYNC_OBSIDIAN: 未配置 OBSIDIAN_VAULT_PATH")
    p = Path(vault)
    if not p.exists():
        raise RuntimeError(f"ERR_SYNC_OBSIDIAN: Vault 路径不存在：{p}")
    return p


def copy_file(path: str | Path, cfg: Dict, sub: str | None = None,
              dest_name: str | None = None) -> str:
    """写入 Vault。

    ``sub`` 覆盖配置里的 ``sub_folder``（Vault 约定各异，例如 Obsidian
    仓库要求「他人内容进 ``raw/<主题>/``、文件名加 ``raw_`` 前缀」，
    此时需要显式指定子目录与目标文件名）。
    """
    path = Path(path)
    vault = resolve_vault(cfg)
    if sub is None:
        sub = cfg.get("knowledge_base", {}).get("obsidian", {}).get("sub_folder", "视频笔记")
    dest_dir = vault / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (dest_name or path.name)
    shutil.copy2(path, dest)
    print(f"[OK] Obsidian 写入：{dest}")
    return str(dest)


def copy_dir(directory: str | Path, cfg: Dict, sub: str | None = None) -> List[str]:
    directory = Path(directory)
    copied = []
    for md in sorted(directory.glob("*.md")):
        try:
            copied.append(copy_file(md, cfg, sub=sub))
        except RuntimeError as e:
            print(str(e))
    return copied


def _parse_args(argv: list[str]):
    """``sync_obsidian.py <file_or_dir> [--sub 子目录] [--name 文件名] [config.yaml]``"""
    positional: list[str] = []
    sub = name = None
    it = iter(argv)
    for a in it:
        if a == "--sub":
            sub = next(it, None)
        elif a.startswith("--sub="):
            sub = a.split("=", 1)[1]
        elif a == "--name":
            name = next(it, None)
        elif a.startswith("--name="):
            name = a.split("=", 1)[1]
        else:
            positional.append(a)
    return positional, sub, name


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: sync_obsidian.py <file_or_dir> [--sub 子目录] [--name 文件名] [config.yaml]")
        return 2
    import common

    positional, sub, name = _parse_args(sys.argv[1:])
    cfg = common.load_config(positional[1]) if len(positional) > 1 else common.load_config()
    p = Path(positional[0])
    try:
        if p.is_dir():
            copy_dir(p, cfg, sub=sub)
        else:
            copy_file(p, cfg, sub=sub, dest_name=name)
        return 0
    except RuntimeError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
