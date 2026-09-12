"""Generic downloader via yt-dlp (Bilibili / Douyin / YouTube / Kuaishou / Xiaohongshu / fallback).

Cookie 策略（渐进降级，依次尝试直到成功）：
  1. ``download.cookie_file`` 指向 Netscape 格式 cookies.txt → ``--cookies``。
     这是**唯一可靠**的方式：Chrome/Edge 127+ 启用了 App-Bound Encryption
     （``v20`` 前缀），yt-dlp 无法解密，即使浏览器已关闭也会报 issue #10927。
  2. **匿名请求**（不加任何 Cookie 参数）。多数公开内容（B站普通画质、YouTube 等）
     无需登录即可下载，且完全不受浏览器锁定 / App-Bound 加密影响，故排在浏览器读取之前。
  3. ``download.cookie_browser``（或 ``auto``）→ ``--cookies-from-browser``。
     ``auto`` 会自动探测本机已安装浏览器。浏览器**正在运行**时 Cookie 库被独占锁定
     （"Could not copy Chrome cookie database"），此时请改用方式 1。

仅在**所有**策略都失败后才抛 ``ERR_DOWNLOAD_FAILED``，错误信息会汇总各次尝试的原因。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict

# yt-dlp 的 --cookies-from-browser 取值 → 本机 User Data 目录（相对 %LOCALAPPDATA% / %APPDATA%）
_WIN_BROWSER_ROOTS: dict[str, list[str]] = {
    "edge": [r"%LOCALAPPDATA%\Microsoft\Edge\User Data"],
    "chrome": [r"%LOCALAPPDATA%\Google\Chrome\User Data"],
    "brave": [r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"],
    "chromium": [r"%LOCALAPPDATA%\Chromium\User Data"],
    "vivaldi": [r"%LOCALAPPDATA%\Vivaldi\User Data"],
    "opera": [r"%APPDATA%\Opera Software\Opera Stable"],
    "firefox": [r"%APPDATA%\Mozilla\Firefox\Profiles"],
}
# 探测顺序：优先本机最常见的
_DETECT_ORDER = ["edge", "chrome", "brave", "chromium", "vivaldi", "opera", "firefox"]


def download(url: str, workdir: Path, cfg: dict) -> Dict:
    workdir.mkdir(parents=True, exist_ok=True)
    dl_cfg = cfg.get("download", {}) or {}
    quality = dl_cfg.get("quality", "1080p")
    timeout = int(dl_cfg.get("timeout", 30))
    proxy = dl_cfg.get("proxy")

    fmt = _format_selector(quality)
    out_tmpl = str(workdir / "%(id)s.%(ext)s")
    base_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--write-info-json",           # 供 _parse_info_json 读取标题/时长等元数据
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
    ]
    if proxy:
        base_cmd += ["--proxy", proxy]

    # 渐进降级：cookies.txt → 匿名 → 浏览器 Cookie，任一成功即返回
    attempts = _cookie_attempts(dl_cfg)
    errors: list[tuple[str, str]] = []

    for label, cookie_args in attempts:
        cmd = base_cmd + cookie_args + [url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 10)
        except subprocess.TimeoutExpired:
            errors.append((label, "yt-dlp 超时"))
            continue
        if proc.returncode == 0:
            videos = sorted(
                p for p in workdir.iterdir() if p.suffix in (".mp4", ".mkv", ".webm", ".mov")
            )
            if videos:
                return {
                    "video_path": str(videos[-1]),
                    "metadata": _parse_info_json(workdir),
                    "cookie_mode": label,
                }
            errors.append((label, "yt-dlp 返回 0 但未找到视频产物"))
            continue
        errors.append((label, proc.stderr or ""))

    raise RuntimeError("ERR_DOWNLOAD_FAILED: " + _explain_errors(errors))


# --------------------------------------------------------------------------- #
# Cookie 解析
# --------------------------------------------------------------------------- #
def _cookie_attempts(dl_cfg: dict) -> list[tuple[str, list[str]]]:
    """返回按优先级排列的 Cookie 尝试列表 ``[(标签, yt-dlp 参数), ...]``。

    顺序：cookies.txt → 匿名 → 浏览器读取。匿名排在浏览器之前，是因为大量公开内容
    （B站普通画质、YouTube 等）本就无需登录，而浏览器读取常因进程锁定或
    App-Bound 加密而失败，把它放在最后可避免"能下却下不了"的误判。
    """
    attempts: list[tuple[str, list[str]]] = []

    # 1) 显式 cookies.txt（可绕过 App-Bound 加密，最稳）
    cf = dl_cfg.get("cookie_file") or os.environ.get("YTDLP_COOKIES_FILE") or ""
    if cf:
        path = Path(os.path.expanduser(str(cf)))
        if path.is_file():
            attempts.append((f"cookie_file:{path.name}", ["--cookies", str(path)]))
        else:
            print(f"[WARN] download.cookie_file 指向的文件不存在，已跳过：{path}")

    # 2) 匿名请求
    attempts.append(("anonymous", []))

    # 3) 浏览器 Cookie（仅在前面都失败时才用）
    browser = str(dl_cfg.get("cookie_browser") or "auto").strip().lower()
    if browser not in ("", "none", "false", "off"):
        if browser == "auto":
            browser = detect_installed_browser() or ""
        if browser:
            attempts.append((f"browser:{browser}", ["--cookies-from-browser", browser]))

    return attempts


def _cookie_args(dl_cfg: dict) -> list[str]:
    """兼容旧调用：返回**首选** Cookie 策略的参数（cookies.txt，其次匿名）。"""
    attempts = _cookie_attempts(dl_cfg)
    return attempts[0][1] if attempts else []


def detect_installed_browser() -> str | None:
    """返回本机已安装浏览器的 yt-dlp 名称（按 _DETECT_ORDER 优先级）。"""
    for name in _DETECT_ORDER:
        for tmpl in _WIN_BROWSER_ROOTS.get(name, []):
            p = Path(os.path.expandvars(tmpl))
            if p.is_dir():
                return name
    return None


def _explain_errors(errors: list[tuple[str, str]]) -> str:
    """汇总多次 Cookie 尝试的失败原因，并给出最有价值的修复建议。"""
    if not errors:
        return "未知错误"

    def last_line(text: str) -> str:
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        return lines[-1] if lines else "unknown"

    summary = "\n".join(f"  [{label}] {last_line(msg)}" for label, msg in errors)
    merged = "\n".join(msg for _, msg in errors).lower()

    if "could not copy" in merged or "could not find" in merged and "cookies database" in merged:
        hint = (
            "浏览器正在运行，Cookie 库被独占锁定。请完全退出该浏览器后重试；"
            "若仍失败（Chrome/Edge 127+ 的 App-Bound 加密无法解密），"
            "请改用 download.cookie_file 指向导出的 cookies.txt。"
        )
    elif "failed to decrypt with dpapi" in merged or "10927" in merged:
        hint = (
            "浏览器 Cookie 使用 App-Bound Encryption（v20），yt-dlp 无法解密。"
            "请在浏览器中安装 *Get cookies.txt LOCALLY* 类扩展导出该站点 cookies.txt，"
            "并把路径写入 download.cookie_file。"
        )
    elif "no video formats found" in merged or "please log in" in merged or "login" in merged:
        hint = (
            "该内容需要登录态（或需会员才能取到该画质）。请配置 download.cookie_file，"
            "或把 download.quality 调低（如 480p）后重试。"
        )
    elif "premium" in merged or "大会员" in merged:
        hint = "该画质需要平台会员。请把 download.quality 调低（如 480p / 720p）后重试。"
    else:
        hint = "请检查链接有效性、网络与代理设置。"

    return f"全部 {len(errors)} 种策略均失败：\n{summary}\n建议：{hint}"


def _explain_error(stderr: str) -> str:
    """把 yt-dlp 的原始报错翻译成可操作的提示（兼容单条错误的旧调用）。"""
    err = (stderr or "").strip()
    lines = [l for l in err.splitlines() if l.strip()]
    last = lines[-1] if lines else "unknown"

    low = err.lower()
    if "could not copy" in low or "could not find" in low and "cookies database" in low:
        return (
            f"{last} —— 浏览器正在运行，Cookie 库被独占锁定。"
            "请完全退出该浏览器后重试；若仍失败（Chrome/Edge 127+ 的 App-Bound 加密无法解密），"
            "请改用 download.cookie_file 指向导出的 cookies.txt。"
        )
    if "failed to decrypt with dpapi" in low or "10927" in low:
        return (
            f"{last} —— 浏览器 Cookie 使用 App-Bound Encryption（v20），yt-dlp 无法解密。"
            "请在浏览器中安装 *Get cookies.txt LOCALLY* 类扩展，导出该站点 cookies.txt，"
            "并把路径写入 download.cookie_file。"
        )
    if "no video formats found" in low:
        return (
            f"{last} —— 该内容需要登录态。请配置 download.cookie_file 或 download.cookie_browser 后重试。"
        )
    return last


def _format_selector(quality) -> str:
    """Build a yt-dlp ``-f`` selector from a quality hint like ``1080p`` / ``best``."""
    q = str(quality or "1080p").strip().lower()
    if q == "best" or not q.rstrip("p").isdigit():
        return "bestvideo+bestaudio/best"
    return f"bestvideo[height<={q.rstrip('p')}]+bestaudio/best"


def _parse_info_json(workdir: Path) -> Dict:
    for f in workdir.glob("*.info.json"):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}
