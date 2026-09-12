#!/usr/bin/env python3
"""Layer 2.5: 弹幕时间轴分析（无字幕视频的降级路径）。

当视频**没有字幕轨**且 ASR 不可用时（如未配置 API Key），完整文字稿无法生成。
但 B 站等平台的弹幕带**视频内时间戳**，是观众对"当时正在播放的画面/声音"的实时
反应，可用于：

1. 定位内容段落与情绪峰值（弹幕密度时间轴）；
2. 反推各段落主题（取该时段最长/信息量最高的弹幕）；
3. 观众情绪画像（高频词统计）。

输出 ``danmaku_stats.json``：``{total, density[], keywords[], segments[]}``。
注意：段落主题属**推断**，笔记中必须标注为「合理推论」，不得冒充文字稿。

用法::

    python scripts/fetch_danmaku.py <url> --out <workdir>
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许直接脚本方式运行
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import ensure_tools_on_path  # type: ignore
else:
    from .common import ensure_tools_on_path

_DANMAKU_RE = re.compile(r'<d p="([^"]+)">([^<]*)</d>')

# 高频无信息词（仅用于词频过滤，不影响原始弹幕保留）
_STOPWORDS = set("""
的 了 是 我 你 他 她 它 我们 你们 他们 这 那 有 在 和 就 都 而 及 与 也 很 到 说 要 会 着
没有 看 不 吧 啊 呀 哦 嗯 哈 哈哈 哈哈哈 给 被 把 让 从 对 里 上 下 中 个 一 二 三
什么 怎么 为什么 这个 那个 还有 就是 但是 因为 所以 如果 可以 一个 一样 一直 好像 觉得
知道 感觉 真的 太 好 太好 牛 厉害 666 233 是的 不是 现在 当时 时候 出来 起来 下去 然后
而且 并且 虽然 只是 才是 这些 那些 一些 很多 太多 有点 非常 特别 十分 极其 超级 最 更
再 又 才 已 已经 正在 将要 能 应该 可能 大概 也许 一定 必须 需要 开始 结束 出现 发生
存在 成为 作为 通过 对于 关于 由于 因此 之后 之前 以前 以后 以来 以内 之外 之间
""".split())


def fetch_danmaku_xml(url: str, workdir: Path, timeout: int = 180) -> Path | None:
    """用 yt-dlp 下载弹幕 xml，返回文件路径（无弹幕时返回 None）。"""
    ensure_tools_on_path()
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "danmaku",
           "--no-warnings", "-o", str(workdir / "%(id)s.%(ext)s"), url]
    subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    cands = sorted(workdir.glob("*.danmaku.xml")) or sorted(workdir.glob("*.xml"))
    return cands[0] if cands else None


def parse_danmaku(xml_path: Path) -> list[tuple[float, str]]:
    """解析弹幕 xml，返回 ``[(秒, 文本), ...]``。"""
    raw = xml_path.read_text(encoding="utf-8", errors="replace")
    items: list[tuple[float, str]] = []
    for m in _DANMAKU_RE.finditer(raw):
        parts = m.group(1).split(",")
        try:
            t = float(parts[0])          # p 属性第 1 位 = 视频内出现时间（秒）
        except (ValueError, IndexError):
            continue
        text = m.group(2).strip()
        if text:
            items.append((t, text))
    return items


def bucket_density(items, bucket_sec: int = 30, top: int = 12) -> list[dict]:
    """弹幕密度时间轴（按 bucket_sec 分桶，返回最热的 top 个区间）。"""
    c = collections.Counter(int(t // bucket_sec) * bucket_sec for t, _ in items)
    return [{"start": b, "end": b + bucket_sec, "count": n} for b, n in c.most_common(top)]


def top_keywords(items, min_count: int = 8, limit: int = 30) -> list[dict]:
    """2–4 字滑窗词频（过滤停用词与子串重叠）。"""
    ngram: collections.Counter = collections.Counter()
    for _, txt in items:
        s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", txt)
        for n in (2, 3, 4):
            for i in range(len(s) - n + 1):
                g = s[i:i + n]
                if g not in _STOPWORDS:
                    ngram[g] += 1
    cand = sorted([(g, n) for g, n in ngram.items() if n >= min_count],
                  key=lambda x: (-x[1], -len(x[0])))
    picked: list[tuple[str, int]] = []
    for g, n in cand:
        if any(g in pg for pg, _ in picked):   # 已是更高频长词的子串则跳过
            continue
        picked.append((g, n))
        if len(picked) >= limit:
            break
    return [{"word": g, "count": n} for g, n in picked]


def segment_samples(items, density: list[dict], bucket_sec: int = 30,
                    per_seg: int = 6) -> list[dict]:
    """各高峰时段的信息量最高（取最长）弹幕样本，用于推断段落主题。"""
    segs = []
    for d in density:
        b, e = d["start"], d["end"]
        seg = [(t, x) for t, x in items if b <= t < e]
        samples = [x for _, x in sorted(seg, key=lambda p: len(p[1]))[-per_seg:]]
        segs.append({"start": b, "end": e, "count": len(seg), "samples": samples})
    return segs


def analyze(url: str, workdir: Path, timeout: int = 180) -> dict | None:
    """一键：下载 → 解析 → 统计。无弹幕时返回 None。"""
    xml = fetch_danmaku_xml(url, workdir, timeout=timeout)
    if not xml:
        return None
    items = parse_danmaku(xml)
    if not items:
        return None
    density = bucket_density(items)
    stats = {
        "total": len(items),
        "xml": str(xml),
        "density": density,
        "keywords": top_keywords(items),
        "segments": segment_samples(items, density),
    }
    (workdir / "danmaku_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="弹幕时间轴分析（无字幕视频降级路径）")
    ap.add_argument("url")
    ap.add_argument("--out", required=True, help="工作目录（产物与 danmaku_stats.json 存放处）")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    stats = analyze(args.url, Path(args.out), timeout=args.timeout)
    if not stats:
        print("[WARN] 未获取到弹幕（该平台无弹幕，或需登录态）。文字稿仍需 ASR。")
        return 1
    print(f"弹幕总数: {stats['total']}")
    print("--- 密度 Top ---")
    for d in stats["density"]:
        mm, ss = divmod(d["start"], 60)
        print(f"  {mm:02d}:{ss:02d}  {d['count']} 条")
    print("--- 高频词 ---")
    print("  " + ", ".join(f"{k['word']}({k['count']})" for k in stats["keywords"][:15]))
    print(f"[OK] 已写入 {Path(args.out) / 'danmaku_stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
