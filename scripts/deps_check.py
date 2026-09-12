#!/usr/bin/env python3
"""Dependency self-check for video_fetch_yjf.

Verifies that required external tools (ffmpeg, yt-dlp) and optional engines
(whisper / cloud ASR) are available before running the pipeline. Exits non-zero
when a hard dependency is missing.
"""
from __future__ import annotations

import shutil
import sys

# Bootstrap tool PATH so ffmpeg/yt-dlp (placed in the isolated venv Scripts dir)
# are discoverable even when this script is run standalone.
try:
    import common  # noqa: F401
    common.ensure_tools_on_path()
except Exception:
    pass

MISSING: list[str] = []


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def check_tool(name: str, hint: str) -> bool:
    ok = _have(name)
    if ok:
        print(f"[OK]   {name}")
    else:
        print(f"[MISS] {name}  -> {hint}")
        MISSING.append(name)
    return ok


def check_python_pkg(name: str, hint: str) -> bool:
    try:
        __import__(name)
        print(f"[OK]   python:{name}")
        return True
    except Exception:
        print(f"[MISS] python:{name}  -> {hint}")
        MISSING.append(f"python:{name}")
        return False


def main() -> int:
    print("== video_fetch_yjf dependency check ==")
    # Hard dependencies
    check_tool("ffmpeg", "安装 FFmpeg 并加入 PATH（音频提取/转码）")
    check_tool("yt-dlp", "pip install yt-dlp  或  uvx yt-dlp@latest")
    # Optional but recommended (NOT hard deps)
    check_python_pkg("yaml", "pip install pyyaml（解析 config.yaml）")
    check_python_pkg("openai", "pip install openai（LLM/云端ASR 调用）")
    # requests 非必需：skill 的 HTTP 调用均使用标准库 urllib，无需 requests
    # ASR engine (optional; absence is informational, not a hard failure)
    whisper_ok = _have("whisper")
    if not whisper_ok:
        try:
            __import__("whisper")
            whisper_ok = True
        except Exception:
            pass
    if not whisper_ok:
        print("[INFO] Whisper 不可用：将依赖云端 ASR（OpenAI/SiliconFlow/DashScope），需配置对应 API Key")

    if MISSING:
        print(f"\n缺失依赖（硬依赖将导致流程中止）：{', '.join(MISSING)}")
        print("请先安装上述依赖后重试。")
        return 1
    print("\n所有硬依赖就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
