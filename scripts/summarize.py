#!/usr/bin/env python3
"""Layer 3.3: LLM summary + PREP structured analysis + transcript segmentation."""
from __future__ import annotations

import os
import json
from typing import Dict

PROMPT_SUMMARY = (
    "请用 100 字以内概括该视频的核心内容，要求涵盖主题、核心观点和关键结论。"
    "仅输出概括文本，不要分点、不要解释。"
)
PROMPT_PREP = (
    "请基于以下内容，用 PREP 法则（Point 观点 -> Reason 理由 -> Example 案例 -> Point 重申）"
    "生成结构化小结。严格按以下模板输出：\n"
    "### 核心观点\n[一句话结论]\n#### 论据1：[分论点]\n- 支撑内容/案例\n"
    "#### 论据2：[分论点]\n- 支撑内容/案例\n### 结论重申\n[回扣核心观点]"
)
PROMPT_SEGMENT = (
    "请将下面的视频文字稿按语义段落整理，内容不可缺损、不可删减，仅做分段与标点优化；"
    "每段前可加一句小标题概括该段要点。直接输出整理后的文字稿。"
)


def _call_llm(prompt: str, context: str, cfg: dict, max_tokens: int = 1024) -> str:
    llm = cfg.get("llm", {}) or {}
    provider = llm.get("provider", "openai")
    model = llm.get("model", "gpt-4o")
    api_key = os.environ.get("OPENAI_API_KEY") or llm.get("api_key")
    base_url = llm.get("base_url") or None
    temperature = float(llm.get("temperature", 0.3))

    if not api_key:
        raise RuntimeError("ERR_SUMMARY_FAILED: 缺少 OPENAI_API_KEY")
    # 当前实现只支持 OpenAI 兼容端点；显式拦住被误配成 anthropic/gemini 的情况，
    # 避免"配了但不生效"的静默失败。
    if provider not in ("openai", "custom"):
        raise RuntimeError(
            f"ERR_SUMMARY_FAILED: 暂不支持的 LLM provider：{provider}"
            "（当前仅支持 openai 与 custom——任何 OpenAI 兼容端点，填 llm.base_url）"
        )

    messages = [{"role": "user", "content": f"{prompt}\n\n---\n{context}"}]
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""
    except Exception as e:  # openai SDK 不可用/调用失败 → 退化为裸 HTTP 请求
        print(f"[WARN] openai SDK 调用失败，改用裸 HTTP：{e}")
        import urllib.request

        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        body = json.dumps(
            {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def summarize(full_text: str, cfg: dict) -> Dict:
    try:
        summary = _call_llm(PROMPT_SUMMARY, full_text, cfg, max_tokens=300)
        prep = _call_llm(PROMPT_PREP, full_text, cfg, max_tokens=800)
        segmented = _call_llm(PROMPT_SEGMENT, full_text, cfg, max_tokens=4096)
    except Exception as e:
        raise RuntimeError(f"ERR_SUMMARY_FAILED: {e}")
    return {"summary": summary.strip(), "prep": prep.strip(), "segmented": segmented.strip()}
