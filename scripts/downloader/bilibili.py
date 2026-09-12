"""Bilibili downloader: yt-dlp core + B站 API metadata enrichment."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from . import generic


def download(url: str, workdir: Path, cfg: dict) -> Dict:
    result = generic.download(url, workdir, cfg)
    meta = result.get("metadata", {}) or {}
    bvid = meta.get("id") or _extract_bvid(url)
    if bvid:
        enriched = _fetch_bili_stat(bvid)
        if enriched:
            meta = {**meta, **enriched}
            result["metadata"] = meta
    return result


def _extract_bvid(url: str) -> str | None:
    import re

    m = re.search(r"BV[0-9A-Za-z]+", url)
    return m.group(0) if m else None


def _fetch_bili_stat(bvid: str) -> Dict:
    """Best-effort enrichment via public B站 API (no key required)."""
    try:
        import urllib.request

        api = f"https://api.bilibili.com/x/web-interface/wbi/view?bvid={bvid}"
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        d = data.get("data", {})
        return {
            "title": d.get("title"),
            "owner": d.get("owner", {}).get("name"),
            "stat": d.get("stat", {}),
            "pubdate": d.get("pubdate"),
            "tags": d.get("tags", []),
        }
    except Exception:
        return {}
