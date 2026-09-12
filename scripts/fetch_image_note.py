#!/usr/bin/env python3
"""图文笔记（小红书 / 通用 SSR）抓取与渲染。

背景：小红书大量笔记是**图文（图集）**而非视频，`type == "normal"` 且无
``video.media.stream``。此时 yt-dlp 会报 ``No video formats found``，整条
「下载 → ASR → 总结」视频管道对它不适用。

本脚本走**另一条路径**：直接解析笔记页 SSR 内嵌的 ``window.__INITIAL_STATE__``
（无需 Cookie），拿到标题/正文/标签/互动数/配图直链，下载图片并渲染结构化成
Markdown 笔记。纯标准库实现，无第三方依赖。

用法::

    python scripts/fetch_image_note.py "<笔记URL>" [--out output]

退出码：0 成功；2 该笔记是视频（应改走 run.py 视频管道）；3 抓取/解析失败。
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")

ERR_NOTE_FETCH_FAILED = "ERR_NOTE_FETCH_FAILED"
ERR_NOTE_IS_VIDEO = "ERR_NOTE_IS_VIDEO"
ERR_NOTE_NO_IMAGES = "ERR_NOTE_NO_IMAGES"

_NOTE_ID_RE = re.compile(r"/(?:discovery/item|explore)/([0-9a-fA-F]{16,32})")


def normalize_url(url: str) -> str:
    """展开 xhslink.com 短链，返回最终 URL。"""
    url = (url or "").strip()
    if "xhslink.com" not in url:
        return url
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl() or url


def note_id_of(url: str) -> Optional[str]:
    m = _NOTE_ID_RE.search(url or "")
    return m.group(1) if m else None


def _fetch_html(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.xiaohongshu.com/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
    if "gzip" in enc:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def parse_note(html: str) -> Dict:
    """从笔记页 HTML 中解析笔记主体数据。"""
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        raise RuntimeError(f"{ERR_NOTE_FETCH_FAILED}: 页面未包含 __INITIAL_STATE__（可能被风控拦截）")
    state = json.loads(m.group(1).replace("undefined", "null"))
    detail = (state.get("note") or {}).get("noteDetailMap") or {}
    if not detail:
        raise RuntimeError(f"{ERR_NOTE_FETCH_FAILED}: noteDetailMap 为空（笔记可能已删除或需登录）")
    return list(detail.values())[0].get("note") or {}


def _clean_desc(desc: str) -> str:
    desc = re.sub(r"\[话题\]#", "", desc or "")
    desc = desc.replace("\t", "")
    return re.sub(r"\n{3,}", "\n\n", desc).strip()


def download_images(images: list, imgdir: Path, timeout: int = 60) -> list:
    imgdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, im in enumerate(images, start=1):
        src = im.get("urlDefault") or im.get("urlPre") or im.get("url")
        if not src:
            continue
        dst = imgdir / f"{i:02d}.jpg"
        try:
            req = urllib.request.Request(src, headers={"User-Agent": UA,
                                                       "Referer": "https://www.xiaohongshu.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dst.write_bytes(r.read())
            saved.append(dst)
        except Exception as e:  # noqa: BLE001 - 单图失败不影响整体
            print(f"[WARN] 图片 #{i} 下载失败: {e}")
    return saved


def build_markdown(note: Dict, rel_img_dir: str = "images") -> str:
    desc = _clean_desc(note.get("desc") or "")
    tags = note.get("tagList") or []
    it = note.get("interactInfo") or {}
    imgs = note.get("imageList") or []
    ts = note.get("time")
    time_str = (datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
                if ts else "")
    title = (note.get("title") or "").strip() or (desc.splitlines()[0] if desc else "小红书笔记")
    nid = note.get("noteId") or ""
    user = (note.get("user") or {}).get("nickname") or ""

    lines = [
        f"# {title}", "",
        f"> **平台**：小红书（图文笔记 · 非视频） · **配图**：{len(imgs)} 张",
        f"> **作者**：{user} · **IP**：{note.get('ipLocation', '')}",
        f"> **发布**：{time_str} · **抓取**：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> **互动**：赞 {it.get('likedCount', '-')} · 藏 {it.get('collectedCount', '-')} "
        f"· 转 {it.get('shareCount', '-')} · 评 {it.get('commentCount', '-')}",
        f"> **原文**：https://www.xiaohongshu.com/discovery/item/{nid}",
        "", "---", "",
        "## 一、正文（原文完整转录）", "", desc, "",
        "## 二、标签", "",
        " · ".join(f"`#{t}`" for t in tags) if tags else "（无）", "",
        "## 三、配图", "",
    ]
    for i, im in enumerate(imgs, start=1):
        lines.append(f"- `{rel_img_dir}/{i:02d}.jpg` — {im.get('width')}x{im.get('height')}")
    lines += [
        "", "---", "",
        "## 四、待补全",
        "",
        "- **评论区**：小红书评论接口需登录签名（`x-s`/`x-t`），无 Cookie 时不采集。",
        "- **图片文字（OCR）**：配图内的文字需 OCR 转为可检索文本。",
        "- **视频管道不适用**：本笔记为图文，无音视频轨，不经过「下载→ASR→总结」流程。",
        "", "---", "",
        "*本笔记由 video-fetch-yjf Skill 的图文笔记路径生成*",
    ]
    return "\n".join(lines)


def fetch(url: str, out_dir: str | os.PathLike, timeout: int = 30) -> Dict:
    """抓取一条图文笔记；若该笔记是视频则抛 ``ERR_NOTE_IS_VIDEO``。"""
    url = normalize_url(url)
    nid = note_id_of(url) or "note"
    note = parse_note(_fetch_html(url, timeout=timeout))

    if note.get("video"):
        raise RuntimeError(f"{ERR_NOTE_IS_VIDEO}: 该笔记含视频轨，请改用 run.py 视频管道")

    imgs = note.get("imageList") or []
    if not imgs:
        raise RuntimeError(f"{ERR_NOTE_NO_IMAGES}: 未找到配图")

    base = Path(out_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    saved = download_images(imgs, base / "images", timeout=timeout)
    md = build_markdown(note)
    (base / "笔记.md").write_text(md, encoding="utf-8")

    return {
        "note_id": note.get("noteId") or nid,
        "has_video": False,
        "image_count": len(saved),
        "note_path": str(base / "笔记.md"),
        "images_dir": str(base / "images"),
    }


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="小红书图文笔记抓取与渲染")
    ap.add_argument("url")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)
    try:
        res = fetch(args.url, args.out)
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return 2 if ERR_NOTE_IS_VIDEO in str(e) else 3
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
