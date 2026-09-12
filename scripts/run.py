#!/usr/bin/env python3
"""video_fetch_yjf — pipeline orchestrator (Layer 1 -> Layer 4).

Usage:
    python scripts/run.py "URL1" "URL2" --config config/config.yaml --output ./output

Implements the four-layer pipeline with per-item graceful degradation
(references/error-codes.md), batch support, and a final verification report.
"""
from __future__ import annotations

import argparse
import shutil
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import common

from downloader import dispatch
import extract_audio
import transcribe
import summarize
import fetch_comments
import render_markdown
import validate_output
import sync_ima
import sync_obsidian


# 产物目录名中的平台缩写（避免 XIAO / BILI 这类截断怪名）
PLATFORM_ABBR = {
    "xiaohongshu": "XHS",
    "bilibili": "BILI",
    "douyin": "DY",
    "youtube": "YT",
    "wechat": "WX",
    "kuaishou": "KS",
    "weibo": "WB",
}


@dataclass
class Report:
    url: str
    platform: str = ""
    status: str = "pending"  # ok | failed | skipped
    note_path: str = ""
    errors: list = field(default_factory=list)
    cost_asr: float = 0.0
    cost_llm: float = 0.0


def _slug(text: str, n: int = 15) -> str:
    text = re.sub(r"[^\w一-鿿]+", "", text)
    return text[:n]


def _build_foldername(meta: dict, platform: str, url: str) -> str:
    """产物目录名：<平台缩写>_<内容ID前8位>_<标题前12字>。

    与手动归档惯例一致（如 ``XHS_6a875b53_汗在哪病就在哪``），
    便于用户在 output/ 下直接按来源定位，而不是散落在 cache/<hash>。
    """
    nid = _slug(str(meta.get("id") or meta.get("note_id") or meta.get("bvid") or ""), 8)
    if not nid:
        nid = _slug(str(abs(hash(url))), 8)
    abbr = PLATFORM_ABBR.get((platform or "").lower(), (platform or "VID").upper()[:4])
    return f"{abbr}_{nid}_{_slug(str(meta.get('title', '视频笔记')), 12)}"


def process_one(url: str, cfg: dict, args) -> Report:
    rep = Report(url=url)
    try:
        # ---- Layer 1: detect ----
        from detect_platform import detect, is_valid

        if not is_valid(url):
            raise RuntimeError("ERR_PLATFORM_UNRECOGNIZED: 非法链接")
        platform = detect(url)
        if not platform:
            raise RuntimeError("ERR_PLATFORM_UNRECOGNIZED: 无法识别平台")
        rep.platform = platform

        # 相对路径统一以「技能包所在目录」为基准（而非 cwd），
        # 否则同一条命令从不同目录跑，产物会一半落在包内、一半落在包外。
        out_dir = Path(args.output)
        if not out_dir.is_absolute():
            out_dir = (common.SKILL_ROOT.parent / out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # 先落临时工作目录；拿到元数据后再重命名为「一条笔记一个目录」的规范名
        tmp_dir = out_dir / ("_tmp_" + _slug(str(abs(hash(url))), 8))
        workdir = tmp_dir / "_work"
        workdir.mkdir(parents=True, exist_ok=True)

        # ---- Layer 2: download ----
        try:
            dl = dispatch(platform, url, workdir, cfg)
        except (RuntimeError, OSError) as e:
            # 微信视频号：Web 侧本就不提供视频流/本地解析服务未起，改走元数据降级
            if platform == "wechat":
                rep.errors.append(f"ERR_WECHAT_NO_VIDEO: {e}")
                return _wechat_meta_fallback(url, out_dir, rep, tmp_dir)
            raise
        video_path = dl["video_path"]
        meta = dl.get("metadata", {}) or {}

        # 元数据到手 → 重命名临时目录为 output/<平台缩写>_<ID>_<标题>/
        note_dir = out_dir / _build_foldername(meta, platform, url)
        if note_dir != tmp_dir:
            if note_dir.exists():
                shutil.rmtree(note_dir)
            tmp_dir.rename(note_dir)
            workdir = note_dir / "_work"
            video_path = str(workdir / Path(video_path).name)

        # ---- Layer 3: audio -> asr -> summary -> comments ----
        audio = extract_audio.extract(video_path, workdir)
        asr = transcribe.transcribe(audio, cfg)
        full_text = asr.get("text", "")
        rep.cost_asr = round(len(full_text) / 1000 * 0.0, 4)  # 实际费用按引擎计费换算

        # 转写产物必须先落盘：后续 LLM / 评论任一环节失败也不丢已付费算力
        try:
            (workdir / "transcript.json").write_text(
                json.dumps(asr, ensure_ascii=False, indent=1), encoding="utf-8")
            (workdir / "transcript.txt").write_text(full_text, encoding="utf-8")
        except OSError as e:  # 落盘失败不影响主流程
            rep.errors.append(f"WARN_TRANSCRIPT_NOT_SAVED: {e}")

        # 无 LLM 密钥时不整体失败：降级为「文字稿已就绪 + 总结待补全」
        try:
            summary = summarize.summarize(full_text, cfg)
        except RuntimeError as e:
            rep.errors.append(str(e))
            head = full_text[:97].strip()
            summary = {
                "summary": (head + "…") if len(full_text) > 100 else head,
                "prep": "（LLM 不可用，PREP 小结待补全；完整文字稿见第四节）",
                "segmented": full_text,
            }
        rep.cost_llm = 0.0

        comments = []
        if not args.skip_comments:
            try:
                comments = fetch_comments.fetch_comments(url, platform)
            except RuntimeError as e:
                rep.errors.append(str(e))

        # build segments from asr segments if available
        segments = [
            {"heading": f"片段{i+1}", "text": s.get("text", ""), "ts": _fmt_ts(s.get("start"))}
            for i, s in enumerate(asr.get("segments", []))
        ] or [{"heading": "全文", "text": summary["segmented"] or full_text, "ts": ""}]

        # ---- Layer 4: render + validate + write ----
        data = {
            "title": meta.get("title", "未命名视频"),
            "platform": platform,
            "url": url,
            "tags": (meta.get("tags") or ["未分类"])[:5],
            "video_date": meta.get("video_date") or meta.get("pubdate") or date.today().isoformat(),
            "archive_date": date.today().isoformat(),
            "duration": _fmt_duration(meta.get("duration")),
            "summary": summary["summary"],
            "prep": summary["prep"],
            "segments": segments,
            "comments": comments,
            # 文件名固定为 笔记.md（与手动归档一致）；H1 用标题本身
            "filename": meta.get("title") or "视频笔记",
        }
        md = render_markdown.render(data)
        note_path = note_dir / "笔记.md"
        note_path.write_text(md, encoding="utf-8")

        issues = validate_output.check(md)
        if issues:
            rep.errors.append("VALIDATION: " + "; ".join(issues))

        # ---- Layer 4.3: sync ----
        if not args.no_sync:
            _sync(note_path, cfg, rep)

        rep.note_path = str(note_path)
        rep.status = "ok" if not issues else "ok_with_warnings"
    except RuntimeError as e:
        rep.status = "failed"
        rep.errors.append(str(e))
    return rep


def _wechat_meta_fallback(url: str, out_dir: Path, rep: "Report",
                          tmp_dir: Path | None = None) -> "Report":
    """微信视频号拿不到视频流时的降级：交付「文案 + 元数据」笔记。

    视频号预览页是 SPA，JS 执行后的 DOM 里带完整正文 / 话题 / 发布时间 /
    作者 / 封面 / 互动数；只有视频流不可得（页面仅「扫码去微信观看」）。
    """
    if tmp_dir and tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 下载失败后不留空壳目录
    try:
        import fetch_wechat_meta as wm

        sph_id = wm.sph_id_of(url) or _slug(str(abs(hash(url))), 8)
        target = out_dir / f"WX_{sph_id}"
        res = wm.fetch(url, target)
        author = _slug((res.get("meta") or {}).get("author", ""), 12)
        final = out_dir / (f"WX_{sph_id}_{author}" if author else f"WX_{sph_id}")
        if author and final != target:
            if final.exists():
                shutil.rmtree(final)
            target.rename(final)
        rep.status = "ok_partial"
        rep.note_path = str((final if author else target) / "笔记.md")
    except RuntimeError as e:
        rep.status = "failed"
        rep.errors.append(str(e))
    return rep


def _sync(note_path: Path, cfg: dict, rep: Report) -> None:
    kb = cfg.get("knowledge_base", {}) or {}
    ima = kb.get("ima", {}) or {}
    obs = kb.get("obsidian", {}) or {}
    if ima.get("enabled") or (ima.get("client_id") and ima.get("api_key")):
        try:
            sync_ima.upload_file(note_path, cfg)
        except (RuntimeError, OSError) as e:
            rep.errors.append(str(e))
    if obs.get("enabled") or obs.get("vault_path"):
        try:
            sync_obsidian.copy_file(note_path, cfg)
        except (RuntimeError, OSError) as e:
            rep.errors.append(str(e))


def _fmt_ts(seconds) -> str:
    if seconds is None:
        return ""
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"{s // 60:02d}:{s % 60:02d}"


def _fmt_duration(d) -> str:
    if not d:
        return ""
    try:
        return str(int(float(d)))
    except (TypeError, ValueError):
        return str(d)


def main() -> int:
    ap = argparse.ArgumentParser(description="video_fetch_yjf pipeline")
    ap.add_argument("urls", nargs="+", help="one or more video share URLs")
    ap.add_argument("--config", default=str(common.DEFAULT_CONFIG))
    ap.add_argument("--output", default="./output",
                    help="产物根目录；相对路径以技能包所在目录为基准（默认 ./output，即包外的 output/）")
    ap.add_argument("--no-sync", action="store_true", help="skip ima/obsidian sync")
    ap.add_argument("--skip-comments", action="store_true")
    ap.add_argument("--no-deps", action="store_true", help="skip dependency check")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    common.setup_logging(args.verbose)
    cfg = common.load_config(args.config)

    if not args.no_deps:
        import deps_check

        if deps_check.main() != 0:
            print("[WARN] 依赖自检未全部通过，继续运行可能失败。")

    reports = [process_one(u, cfg, args) for u in args.urls]

    # ---- verification report ----
    print("\n================ 下载验证报告 ================")
    ok = sum(1 for r in reports if r.status.startswith("ok"))
    failed = sum(1 for r in reports if r.status == "failed")
    skipped = sum(1 for r in reports if r.status == "skipped")
    for r in reports:
        print(f"[{r.status.upper()}] {r.platform or '?'}  {r.url}")
        if r.note_path:
            print(f"    -> {r.note_path}")
        for e in r.errors:
            print(f"    ! {e}")
    print(f"成功 {ok} / 失败 {failed} / 跳过 {skipped}")
    print(f"ASR 估算费用：¥{sum(r.cost_asr for r in reports):.4f}   "
          f"LLM 估算费用：¥{sum(r.cost_llm for r in reports):.4f}")
    print("=============================================")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
