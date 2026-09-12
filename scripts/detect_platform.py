#!/usr/bin/env python3
"""Layer 1: platform detection and link validation."""
from __future__ import annotations

import sys
import re
from urllib.parse import urlparse

# Ordered (host_substring, platform) matchers.
PLATFORM_RULES = [
    ("channels.weixin.qq.com", "wechat"),
    ("weixin.qq.com", "wechat"),
    ("xiaohongshu.com", "xiaohongshu"),
    ("xhslink.com", "xiaohongshu"),
    ("bilibili.com", "bilibili"),
    ("b23.tv", "bilibili"),
    ("douyin.com", "douyin"),
    ("v.douyin.com", "douyin"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("kuaishou.com", "kuaishou"),
]


def detect(url: str) -> str | None:
    """Return platform name for a URL, or None if unrecognized."""
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    for substr, platform in PLATFORM_RULES:
        if substr in host:
            return platform
    return None


def is_valid(url: str) -> bool:
    return bool(re.match(r"^https?://", url.strip(), re.IGNORECASE))


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: detect_platform.py <url>")
        return 2
    url = sys.argv[1].strip()
    if not is_valid(url):
        print("ERR_PLATFORM_UNRECOGNIZED: not a valid http(s) URL")
        return 1
    plat = detect(url)
    if not plat:
        print("ERR_PLATFORM_UNRECOGNIZED: no matching platform rule")
        return 1
    print(plat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
