"""WeChat Channels (微信视频号) downloader adapter.

Primary: open-source `wx_channels_download` local API (/api/channels/parse_sph).
Fallback: Apify WeChat Channels Video Downloader (requires APIFY token).

Requires an external service to be available; this adapter orchestrates the HTTP
calls and returns the resolved direct video URL for download. Download of the
resolved URL is performed with yt-dlp / requests.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from typing import Dict


def _http_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url: str, workdir: Path, cfg: dict) -> Dict:
    workdir.mkdir(parents=True, exist_ok=True)
    server = (cfg.get("download", {}) or {}).get("wechat_server") or os.environ.get(
        "WX_CHANNELS_SERVER", "http://127.0.0.1:8080"
    )

    # Primary: local wx_channels_download server
    try:
        resp = _http_json(f"{server}/api/channels/parse_sph", {"url": url})
        video_url = resp.get("data", {}).get("video_url") or resp.get("video_url")
        if not video_url:
            raise RuntimeError("no video_url in response")
    # 注意：本地服务不可达时抛的是 ConnectionResetError/ConnectionRefusedError，
    # 它们属于 OSError 而 **不是** urllib.error.URLError，必须一并捕获，
    # 否则 run.py 的降级分支（微信元数据路径）根本进不去。
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        # Fallback: Apify (best-effort, requires token)
        apify_token = os.environ.get("APIFY_TOKEN")
        if not apify_token:
            raise RuntimeError(
                "ERR_DOWNLOAD_FAILED: 微信视频号解析服务不可用，且未配置 APIFY_TOKEN 备选；"
                f"原因：{e}"
            )
        video_url = _apify_fallback(url, apify_token)

    return _fetch_video(video_url, workdir, cfg)


def _apify_fallback(url: str, token: str) -> str:
    actor = "agentflow~wechat-channels-video-downloader"
    run_url = f"https://api.apify.com/v2/acts/{actor}/runs"
    # 任务需 POST 提交并轮询 dataset；当前为占位实现，端点写在这里便于后续补齐。
    raise RuntimeError(
        "ERR_DOWNLOAD_FAILED: Apify 备选需提交任务并轮询 dataset，尚未实现；"
        f"提交端点：{run_url}（token 走 Authorization）。详见 references/platform-apis.md"
    )


def _fetch_video(video_url: str, workdir: Path, cfg: dict) -> Dict:
    out = workdir / "wechat_video.mp4"
    proxy = (cfg.get("download", {}) or {}).get("proxy")
    cmd = ["yt-dlp", "-o", str(out), video_url]
    if proxy:
        cmd += ["--proxy", proxy]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except Exception as e:
        raise RuntimeError(f"ERR_DOWNLOAD_FAILED: {e}")
    return {"video_path": str(out), "metadata": {"source": "wechat"}}
