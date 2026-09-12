"""Video downloader adapters (Layer 2).

Each adapter exposes ``download(url, workdir, cfg) -> dict`` returning at least
``{"video_path": <path>, "metadata": {...}}``. Adapters degrade gracefully and
raise ``RuntimeError`` with an ERR_* style message on failure so the orchestrator
can apply the grading strategy from references/error-codes.md.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict

from . import (
    wechat,
    xiaohongshu,
    bilibili,
    generic,
)

REGISTRY: Dict[str, Callable] = {
    "wechat": wechat.download,
    "xiaohongshu": xiaohongshu.download,
    "bilibili": bilibili.download,
    "douyin": generic.download,
    "youtube": generic.download,
    "kuaishou": generic.download,
}


def dispatch(platform: str, url: str, workdir: str | os.PathLike, cfg: dict) -> dict:
    fn = REGISTRY.get(platform)
    if fn is None:
        raise RuntimeError("ERR_PLATFORM_UNRECOGNIZED: no adapter for " + str(platform))
    return fn(url, Path(workdir), cfg)
