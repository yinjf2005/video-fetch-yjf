#!/usr/bin/env python3
"""Layer 3.1: extract audio via FFmpeg."""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

# Make ffmpeg discoverable on PATH (isolated venv Scripts dir).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

common.ensure_tools_on_path()


def extract(video_path: str, out_dir: str | Path, timeout: int = 600) -> str:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / (Path(video_path).stem + ".mp3")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ERR_AUDIO_EXTRACT: {e.stderr[-300:] if e.stderr else e}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ERR_AUDIO_EXTRACT: ffmpeg 超时")
    return str(audio_path)


def main() -> int:
    import sys

    if len(sys.argv) < 2:
        print("Usage: extract_audio.py <video_path> [out_dir]")
        return 2
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(extract(sys.argv[1], out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
