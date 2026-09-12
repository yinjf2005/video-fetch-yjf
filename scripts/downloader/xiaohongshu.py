"""Xiaohongshu (小红书) downloader adapter.

Primary : yt-dlp 原生 XiaoHongShu 提取器（借用浏览器登录态 Cookie，无需外部服务）。
Fallback: social-media-copilot HTTP 接口（配置 ``download.xiaohongshu_endpoint``，
          默认 ``http://127.0.0.1:8090/api/video``；仅在 yt-dlp 失败时尝试）。
Last    : Apify RedNote Video Downloader（需 ``APIFY_TOKEN``，按 dataset 轮询）。

yt-dlp / ffmpeg 需在 PATH 上；``scripts/common.ensure_tools_on_path()`` 会把隔离
venv 的 Scripts 目录注入 PATH（``run.py`` 启动时已生效）。
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict

from . import generic


def download(url: str, workdir: Path, cfg: dict) -> Dict:
    """Resolve and download a 小红书 video.

    Returns ``{"video_path": str, "metadata": {...}}``; raises ``RuntimeError``
    with an ``ERR_DOWNLOAD_FAILED`` message when every resolver fails.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    url = normalize_url(url)
    attempts: list[str] = []

    # ---- 1) 首选：yt-dlp（原生 XiaoHongShu 提取器，复用通用下载器逻辑）----
    try:
        result = generic.download(url, workdir, cfg)
        meta = result.get("metadata") or {}
        meta["source"] = "xiaohongshu"
        meta["resolver"] = "yt-dlp"
        result["metadata"] = meta
        return result
    except Exception as e:  # noqa: BLE001 - 降级到下一解析器
        attempts.append(f"yt-dlp: {e}")

    # ---- 2) 备选：social-media-copilot / 任意兼容解析接口（可选）----
    dl_cfg = cfg.get("download", {}) or {}
    endpoint = dl_cfg.get("xiaohongshu_endpoint") or os.environ.get("XHS_ENDPOINT")
    if endpoint:
        try:
            return _via_endpoint(endpoint, url, workdir, cfg)
        except Exception as e:  # noqa: BLE001
            attempts.append(f"endpoint({endpoint}): {e}")

    # ---- 3) 兜底：Apify（需令牌，按 dataset 轮询）----
    if os.environ.get("APIFY_TOKEN"):
        attempts.append("apify: 需轮询 dataset，参考 references/platform-apis.md")
    else:
        attempts.append("apify: 未配置 APIFY_TOKEN")

    raise RuntimeError("ERR_DOWNLOAD_FAILED: 小红书下载失败；" + " | ".join(attempts))


def normalize_url(url: str) -> str:
    """Trim whitespace; keep the URL otherwise intact.

    yt-dlp follows ``xhslink.com`` short-link redirects and understands the
    ``xsec_token`` query parameter, so no manual rewriting is required.
    """
    return (url or "").strip()


# --------------------------------------------------------------------------- #
# Fallback: external resolver endpoint (social-media-copilot / compatible)
# --------------------------------------------------------------------------- #
def _via_endpoint(endpoint: str, url: str, workdir: Path, cfg: dict) -> Dict:
    resp = _http_json(endpoint, {"url": url})
    video_url = (resp.get("data") or {}).get("url") or resp.get("video_url")
    if not video_url:
        raise RuntimeError("no url in resolver response")

    out = workdir / "xhs_video.mp4"
    proxy = (cfg.get("download", {}) or {}).get("proxy")
    cmd = ["yt-dlp", "-o", str(out), video_url]
    if proxy:
        cmd += ["--proxy", proxy]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"解析到直链后下载失败：{e}")
    return {"video_path": str(out), "metadata": {"source": "xiaohongshu", "resolver": "endpoint"}}


def _http_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
