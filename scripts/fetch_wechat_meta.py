#!/usr/bin/env python3
"""微信视频号（WeChat Channels）**元数据抓取**路径。

背景与定位
----------
视频号的分享链接（``https://weixin.qq.com/sph/<id>``）在浏览器里会 302 到
``https://channels.weixin.qq.com/finder-preview/pages/sph?id=<id>``，该页是
**纯前端 SPA**：静态 HTML 只有 2.4 KB（含一个 ``<title>视频号</title>``），
JS 执行后 DOM 约 26 KB，里面其实**带着完整的笔记元数据**——正文、话题、
发布时间、作者、头像、封面图、互动数。

而 **视频流本体不在 Web 侧**：页面同时渲染「可扫码前往微信观看此内容」的
二维码浮层，DOM 中没有 ``<video>`` 元素，yt-dlp 也明确不支持该域名
（``ERROR: Unsupported URL``）。因此：

- 能拿：完整文案 + 全部元数据 + 封面 + 头像（**无需登录、无需任何外部服务**）
- 拿不到：视频 / 音频 / 文字稿（需 wx_channels_download 本地服务或 Apify）

本脚本即「元数据降级路径」：在 `downloader/wechat.py` 拿不到视频时，
至少交付一份**内容完整、只缺音视频**的笔记，而不是整条任务失败。

实现
----
复用本机已装的 Chromium 系浏览器（Edge / Chrome / Brave / Chromium）的
``--headless=new --dump-dom --virtual-time-budget=N`` 渲染后取 DOM，
纯标准库解析，**不安装 playwright / selenium**，也不需要登录态。

用法::

    python scripts/fetch_wechat_meta.py "https://weixin.qq.com/sph/ASi4Km47R7" [--out output]

退出码：0 成功；3 抓取/解析失败；4 本机无可用浏览器。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Optional

ERR_NO_BROWSER = "ERR_WECHAT_NO_BROWSER"
ERR_META_FAILED = "ERR_WECHAT_META_FAILED"

_SPH_ID_RE = re.compile(r"/sph/([A-Za-z0-9_-]{6,64})")
_PREVIEW_URL = "https://channels.weixin.qq.com/finder-preview/pages/sph?id={id}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")

# 互动数图标 -> 中文名（视频号 web 预览页的图标语义，实测确认）
_ICON_LABEL = {
    "thumb": "点赞",
    "share": "转发",
    "heart": "收藏",
    "bubble": "评论",
}


def sph_id_of(url: str) -> Optional[str]:
    m = _SPH_ID_RE.search(url or "")
    return m.group(1) if m else None


# ------------------------------------------------------------------ browser
def _browser_candidates() -> list[Path]:
    import os

    roots = [
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    rel = [
        (r"Microsoft\Edge\Application\msedge.exe", "edge"),
        (r"Google\Chrome\Application\chrome.exe", "chrome"),
        (r"BraveSoftware\Brave-Browser\Application\brave.exe", "brave"),
        (r"Chromium\Application\chrome.exe", "chromium"),
    ]
    found: list[Path] = []
    for root in roots:
        if not root:
            continue
        for r, _name in rel:
            p = Path(root) / r
            if p.is_file():
                found.append(p)
    return found


def _render_dom(url: str, timeout: int = 180, budget_ms: int = 12000) -> str:
    """用本机浏览器无头渲染并返回 DOM。"""
    cands = _browser_candidates()
    if not cands:
        raise RuntimeError(
            f"{ERR_NO_BROWSER}: 本机未找到 Edge/Chrome/Brave/Chromium，"
            "无法渲染视频号预览页（SPA）。请安装其一后重试，或改用 "
            "wx_channels_download / Apify 通道取视频。"
        )
    profile = tempfile.mkdtemp(prefix="vfy_headless_")
    cmd = [
        str(cands[0]), "--headless=new", "--disable-gpu", "--no-sandbox",
        "--disable-extensions", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}", f"--virtual-time-budget={budget_ms}",
        "--dump-dom", url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{ERR_META_FAILED}: 浏览器渲染超时（{timeout}s）")
    dom = r.stdout or ""
    if len(dom) < 5000:  # 静态壳子 ~2.4KB，渲染后 ~26KB
        raise RuntimeError(
            f"{ERR_META_FAILED}: 渲染产物仅 {len(dom)} 字节，疑似 JS 未执行或页面风控"
        )
    return dom


# ------------------------------------------------------------------- parsing
def _one(pattern: str, dom: str, group: int = 1) -> str:
    m = re.search(pattern, dom, re.S)
    return html.unescape(m.group(group)).strip() if m else ""


def parse_meta(dom: str) -> Dict:
    desc = _one(r'class="feed-desc-wrap[^"]*"[^>]*>(.*?)</div>', dom)
    desc = re.sub(r"<[^>]+>", "", desc).strip()
    if not desc:
        raise RuntimeError(f"{ERR_META_FAILED}: 未解析到正文（feed-desc-wrap）")

    # 视频号正文里的话题形如「#星空AI观察 #AI时代 #企业管理」（**无闭合 #**），
    # 且可能出现正文末尾连续话题；只取末尾连续段，避免误吞正文。
    trailing = re.search(r"((?:#[^\s#]+\s*)+)$", desc)
    tags = re.findall(r"#([^\s#]+)", trailing.group(1)) if trailing else []
    body = (desc[: trailing.start()].strip() if trailing else desc).strip()

    # 互动数：按 图标 -> 数字 的先后顺序配对
    counts: Dict[str, str] = {}
    for m in re.finditer(
        r'class="i-weui:([a-z]+)-regular".*?class="operate-item-text">\s*([0-9.万亿]+)\s*<',
        dom, re.S,
    ):
        label = _ICON_LABEL.get(m.group(1), m.group(1))
        counts.setdefault(label, m.group(2))

    cover = ""
    m = re.search(r'src="(https://finder\.video\.qq\.com/[^"]+)"', dom)
    if m:
        cover = html.unescape(m.group(1))
    avatar = ""
    m = re.search(r'class="avatar".*?src="([^"]+)"', dom, re.S)
    if m:
        avatar = html.unescape(m.group(1))

    return {
        "desc": body,
        "tags": tags,
        "create_time": _one(r'class="feed-create-time-wrap"[^>]*>(.*?)</div>', dom),
        "author": _one(r'class="author-name"[^>]*>(.*?)</div>', dom),
        "cover": cover,
        "avatar": avatar,
        "counts": counts,
        "playable_in_browser": "<video" in dom,
    }


def _save(url: str, dst: Path) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Referer": "https://channels.weixin.qq.com/"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dst.write_bytes(r.read())
        return True
    except Exception as e:  # noqa: BLE001 - 图片失败不影响主体
        print(f"[WARN] 下载失败 {url[:60]}…: {e}")
        return False


def _slug(text: str, n: int = 12) -> str:
    return re.sub(r"[^\w一-鿿]+", "", text or "")[:n]


def build_markdown(meta: Dict, sph_id: str, url: str, cover_rel: str = "") -> str:
    import datetime

    tags = " · ".join(f"`#{t}`" for t in meta["tags"]) or "（无）"
    counts = meta["counts"]
    cnt = " · ".join(f"{k} {v}" for k, v in counts.items()) or "（未解析到）"
    body_paras = [p.strip() for p in re.split(r"(?<=[。！？])", meta["desc"]) if p.strip()]
    title = _slug(body_paras[0], 20) if body_paras else "视频号笔记"

    lines = [
        f"# 【视频号】{meta['author'] or '未知作者'} · {meta['create_time'] or '未知时间'}", "",
        f"> **平台**：微信视频号 · **作者**：{meta['author'] or '-'} · **发布**：{meta['create_time'] or '-'}",
        f"> **原文**：{url}",
        f"> **互动**：{cnt}",
        f"> **抓取**：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · 由 video-fetch-yjf Skill 生成",
        "",
        "---", "",
        "## 一、元数据（已知事实）", "",
        "| 项 | 值 |", "|---|---|",
        f"| 标题 | {title} |",
        f"| 来源 | 微信视频号 · {meta['author'] or '-'} |",
        f"| 视频发布日期 | {meta['create_time'] or '-'} |",
        f"| 内容存档日期 | {datetime.datetime.now().strftime('%Y-%m-%d')} |",
        f"| 分享 ID | {sph_id} |",
        f"| 标签 | {' / '.join(meta['tags']) or '-'} |",
        f"| 互动 | {cnt} |",
        f"| 封面 | {cover_rel or '（未下载）'} |",
        "| 视频流 | **不可得**：Web 预览页不提供播放（页面含「可扫码前往微信观看」二维码浮层，DOM 无 `<video>`），yt-dlp 亦不支持该域名 |",
        "", "---", "",
        "## 二、文案正文（原文完整转录 · 已知事实）", "",
    ]
    for p in body_paras:
        lines += [p, ""]
    lines += [
        "## 三、话题标签", "",
        tags, "",
        "---", "",
        "## 四、待补全（视频 / 音频 / 文字稿）", "",
        "本条为**元数据降级产出**：Web 侧拿不到视频流，故无法做 ASR 转写。补齐路径三选一：",
        "",
        "1. **本地解析服务**：部署 `wx_channels_download`，配置 `download.wechat_server`"
        "（默认 `http://127.0.0.1:8080`）后重跑 `scripts/run.py <链接>`；",
        "2. **云端兜底**：设置 `APIFY_TOKEN`，走 Apify `agentflow~wechat-channels-video-downloader`；",
        "3. **人工录制**：手机/PC 微信打开该视频号内容录屏，把 mp4 放到本目录后执行：",
        "   ```bash",
        "   python scripts/extract_audio.py <video.mp4> <工作目录>",
        "   python scripts/transcribe.py <audio.mp3> config/config.yaml",
        "   ```",
        "",
        "补齐后按本 Skill 的四层管道补上「内容总结 / PREP 小结 / 完整文字稿 / 热门评论」四节即可。",
        "", "---", "",
        "*本笔记由 video-fetch-yjf Skill 的微信视频号元数据降级路径生成*",
    ]
    return "\n".join(lines)


def fetch(url: str, out_dir: str, timeout: int = 180) -> Dict:
    sph_id = sph_id_of(url)
    if not sph_id:
        raise RuntimeError(f"{ERR_META_FAILED}: 链接中未找到视频号分享 ID（/sph/<id>）")
    dom = _render_dom(_PREVIEW_URL.format(id=sph_id), timeout=timeout)
    meta = parse_meta(dom)

    base = Path(out_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    cover_rel = ""
    if meta["cover"]:
        if _save(meta["cover"], base / "封面.jpg"):
            cover_rel = "封面.jpg"
    if meta["avatar"]:
        _save(meta["avatar"], base / "头像.jpg")

    md = build_markdown(meta, sph_id, url, cover_rel)
    (base / "笔记.md").write_text(md, encoding="utf-8")
    return {"sph_id": sph_id, "meta": meta, "note_path": str(base / "笔记.md")}


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="微信视频号元数据抓取（无需登录/外部服务）")
    ap.add_argument("url")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)
    try:
        res = fetch(args.url, args.out)
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return 4 if ERR_NO_BROWSER in str(e) else 3
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
