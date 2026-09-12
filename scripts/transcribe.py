#!/usr/bin/env python3
"""Layer 3.2: speech-to-text.

Backend 优先级建议（**无需任何 API Key** 亦可跑通）：

1. ``faster-whisper``（本地离线，CTranslate2 + int8，CPU 可跑）——推荐默认。
   支持 VAD 分段 + **逐段自动语言检测**，可正确处理"中文主持 + 英文受访"这类
   中英混说场景；若强制单一语言，会把另一种语言的语音幻觉式硬译（实测教训）。
2. ``openai``（Whisper API，需 OPENAI_API_KEY，与 LLM 共用同一把 key）。
3. ``siliconflow`` / ``dashscope`` 云端 ASR（需对应 key）。

Returns {"text": <full transcript>, "segments": [...]}. 失败按 error-codes 降级。
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List


def transcribe(audio_path: str, cfg: dict) -> Dict:
    asr = cfg.get("asr", {}) or {}
    primary = asr.get("primary", "whisper")
    fallback = asr.get("fallback")

    try:
        if primary == "faster-whisper":
            return _faster_whisper(audio_path, asr)
        if primary == "openai":
            return _openai_asr(audio_path, cfg)
        if primary == "whisper":
            return _whisper(audio_path, asr.get("whisper_model", "large-v3-turbo"))
        if primary in ("siliconflow", "dashscope"):
            return _cloud(audio_path, primary, cfg)
    except Exception as e:
        print(f"[WARN] primary ASR ({primary}) failed: {e}")

    if fallback:
        try:
            return _cloud(audio_path, fallback, cfg)
        except Exception as e:
            raise RuntimeError(f"ERR_ASR_FAILED: 主引擎与备选均失败；{e}")

    raise RuntimeError("ERR_ASR_FAILED: 未配置可用 ASR 引擎")


def _faster_whisper(audio_path: str, asr: dict) -> Dict:
    """Local offline ASR via faster-whisper (CTranslate2). No API key needed.

    ``asr.faster_whisper`` 配置项：
      - ``model_dir``：CT2 模型目录（默认 ``~/.workbuddy/binaries/whisper/large-v3-turbo``，
        可用环境变量 ``WHISPER_MODEL_DIR`` 覆盖）
      - ``compute_type``：``int8``（CPU 推荐）/ ``float16`` / ``float32``
      - ``device``：``cpu`` / ``cuda``
      - ``segment_lang_detect``：是否按 VAD 分段后**逐段检测语言**（默认 True）。
        中英混说务必开启，否则另一种语言会被幻觉式硬译。
      - ``beam_size``：默认 5

    模型获取：HuggingFace 主站不可达时（实测 502），可用镜像
    ``https://hf-mirror.com``，例如 ``mobiuslabsgmbh/faster-whisper-large-v3-turbo``。
    """
    try:
        import numpy as np  # noqa: F401
        from faster_whisper import WhisperModel
        from faster_whisper.audio import decode_audio  # noqa: F401  (依赖预检)
    except Exception as e:
        raise RuntimeError(
            f"ERR_ASR_FAILED: faster-whisper 不可用（{e}）。"
            "请先 `pip install faster-whisper` 并下载 CT2 模型到 model_dir"
        )

    fw = asr.get("faster_whisper", {}) or {}
    default_dir = os.path.join(
        os.path.expanduser("~"), ".workbuddy", "binaries", "whisper", "large-v3-turbo")
    model_dir = fw.get("model_dir") or os.environ.get("WHISPER_MODEL_DIR") or default_dir
    if not os.path.isdir(model_dir):
        raise RuntimeError(f"ERR_ASR_FAILED: 模型目录不存在：{model_dir}")

    model = WhisperModel(model_dir,
                         device=fw.get("device", "cpu"),
                         compute_type=fw.get("compute_type", "int8"),
                         cpu_threads=fw.get("cpu_threads") or (os.cpu_count() or 4))
    beam = int(fw.get("beam_size", 5))

    if fw.get("segment_lang_detect", True):
        return _fw_segmented(model, audio_path, beam)

    segments, info = model.transcribe(audio_path, beam_size=beam,
                                      vad_filter=True,
                                      condition_on_previous_text=False)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments]
    return {"text": " ".join(s["text"] for s in segs), "segments": segs,
            "language": getattr(info, "language", None)}


def _fw_segmented(model, audio_path: str, beam: int) -> Dict:
    """VAD 分段 + 逐段自动语言检测：让中英各归其位。"""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    SR = 16000
    audio = decode_audio(audio_path, sampling_rate=SR)
    ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400))

    # 合并相邻语音段：间隔 < 1.5s 且块长 <= 25s
    blocks: list[list[int]] = []
    for t in ts:
        s, e = t["start"], t["end"]
        if blocks and s - blocks[-1][1] < 1.5 * SR and (blocks[-1][1] - blocks[-1][0]) < 25 * SR:
            blocks[-1][1] = e
        else:
            blocks.append([s, e])

    segs: List[Dict] = []
    langs: List[str] = []
    for s, e in blocks:
        try:
            parts, info = model.transcribe(audio[s:e], language=None, beam_size=beam,
                                           condition_on_previous_text=False)
        except Exception as e2:  # noqa: BLE001 - 单块失败不中止整条音轨
            print(f"[WARN] ASR 段落 {round(s/SR,1)}s 失败：{e2}")
            continue
        text = " ".join(x.text.strip() for x in parts).strip()
        if not text:
            continue
        segs.append({"start": round(s / SR, 2), "end": round(e / SR, 2),
                     "lang": info.language, "text": text})
        langs.append(info.language)

    if not segs:
        raise RuntimeError("ERR_ASR_FAILED: faster-whisper 未产出任何文本")
    dominant = max(set(langs), key=langs.count) if langs else None
    return {"text": " ".join(x["text"] for x in segs), "segments": segs,
            "language": dominant}


def _whisper(audio_path: str, model: str) -> Dict:
    if subprocess.run(["yt-dlp", "--version"], capture_output=True).returncode == 0:
        pass  # placeholder; whisper invoked below
    cmd = ["whisper", audio_path, "--model", model, "--output_format", "json"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=True)
    except FileNotFoundError:
        # fallback to openai-whisper python package
        return _whisper_python(audio_path, model)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"whisper cli failed: {e.stderr[-300:] if e.stderr else e}")
    # parse json output
    import json
    from pathlib import Path

    jf = Path(audio_path).with_suffix(".json")
    if jf.exists():
        data = json.loads(jf.read_text(encoding="utf-8"))
        return {"text": data.get("text", ""), "segments": data.get("segments", [])}
    raise RuntimeError("ERR_ASR_FAILED: whisper 未产出 json")


def _whisper_python(audio_path: str, model: str) -> Dict:
    try:
        import whisper  # type: ignore
    except Exception as e:
        raise RuntimeError(f"ERR_ASR_FAILED: openai-whisper 不可用：{e}")
    m = whisper.load_model(model)
    res = m.transcribe(audio_path)
    return {"text": res.get("text", ""), "segments": res.get("segments", [])}


def _openai_asr(audio_path: str, cfg: dict) -> Dict:
    """Transcribe via OpenAI Whisper API (requires OPENAI_API_KEY).

    Driven by the same key used for LLM summarization, so a single
    OPENAI_API_KEY covers both 转写与总结.
    """
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY") or (cfg.get("llm", {}) or {}).get("api_key", "")
    if not key:
        raise RuntimeError("ERR_ASR_FAILED: 缺少 OPENAI_API_KEY")
    model = (cfg.get("asr", {}) or {}).get("openai_asr_model", "whisper-1")
    base_url = (cfg.get("llm", {}) or {}).get("base_url") or None
    client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(model=model, file=f)
    text = getattr(resp, "text", "") or ""
    return {"text": text, "segments": []}


def _cloud(audio_path: str, provider: str, cfg: dict) -> Dict:
    """Call SiliconFlow / DashScope ASR. Requires corresponding API key."""
    if provider == "siliconflow":
        key = os.environ.get("SILICONFLOW_API_KEY")
        if not key:
            raise RuntimeError("ERR_ASR_FAILED: 缺少 SILICONFLOW_API_KEY")
    else:  # dashscope
        key = os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("ERR_ASR_FAILED: 缺少 DASHSCOPE_API_KEY")
    # Placeholder HTTP call — wire to the provider's ASR endpoint.
    # Implementation depends on the chosen provider SDK; kept defensive here.
    raise RuntimeError(
        f"ERR_ASR_FAILED: {provider} ASR 调用未实现，请在 transcribe.py 中接入对应 SDK"
    )


def main() -> int:
    import sys, json

    if len(sys.argv) < 2:
        print("Usage: transcribe.py <audio_path> [config.yaml]")
        return 2
    import common

    cfg = common.load_config(sys.argv[2]) if len(sys.argv) > 2 else common.load_config()
    result = transcribe(sys.argv[1], cfg)
    print(json.dumps(result, ensure_ascii=False)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
