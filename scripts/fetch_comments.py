#!/usr/bin/env python3
"""Layer 2.3: fetch top-5 hottest comments (MediaCrawler best-effort)."""
from __future__ import annotations

import sys
from typing import Dict, List


def fetch_comments(url: str, platform: str, top_n: int = 5) -> List[Dict]:
    """Return list of {"content", "likes", "user"} sorted by likes desc.

    Uses MediaCrawler when available. Platforms without a working crawler return
    an empty list and the orchestrator skips the comments module (ERR_COMMENTS_FAILED).
    """
    try:
        # MediaCrawler exposes per-platform entry points; invoke defensively.
        import media_crawler  # type: ignore

        raw = media_crawler.run(platform=platform, url=url)
    except Exception as e:
        print(f"[WARN] comments fetch unavailable ({platform}): {e}")
        raise RuntimeError(f"ERR_COMMENTS_FAILED: 评论采集不可用；{e}")

    items = [
        {"content": r.get("content", ""), "likes": int(r.get("likes", 0) or 0), "user": r.get("user", "")}
        for r in (raw or [])
    ]
    items.sort(key=lambda x: x["likes"], reverse=True)
    return items[:top_n]


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: fetch_comments.py <url> <platform>")
        return 2
    try:
        res = fetch_comments(sys.argv[1], sys.argv[2])
        print(json.dumps(res, ensure_ascii=False))
    except RuntimeError as e:
        print(str(e))
        return 1
    return 0


if __name__ == "__main__":
    import json

    raise SystemExit(main())
