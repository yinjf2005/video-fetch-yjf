#!/usr/bin/env python3
"""Layer 4.1: render the Markdown note from templates/note_template.md."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_ROOT / "templates" / "note_template.md"


def _render_transcript(segments: List[Dict], with_ts: bool = True) -> str:
    parts = []
    for i, seg in enumerate(segments, 1):
        heading = seg.get("heading") or f"段落{i}"
        ts = f" [{seg['ts']}]" if (with_ts and seg.get("ts")) else ""
        parts.append(f"### 段落{i}：{heading}{ts}\n{seg.get('text', '')}")
    return "\n\n".join(parts)


def _render_comments(comments: List[Dict], top_n: int = 5) -> str:
    rows = []
    for i, c in enumerate(comments[:top_n], 1):
        content = (c.get("content") or "").replace("\n", " ").replace("|", "/")
        rows.append(f"| {i} | {content} | {c.get('likes', 0)} |")
    if not rows:
        rows.append("| - | 该平台暂不支持评论采集 / 评论数据不可得 | - |")
    return "\n".join(rows)


def render(data: Dict, template_path: Path | None = None) -> str:
    tpl = (template_path or TEMPLATE).read_text(encoding="utf-8")

    tags = data.get("tags", []) or []
    tags_display = " ".join(f"#{t}" for t in tags) or "#未分类"
    tags_inline = ", ".join(f'"{t}"' for t in tags) or '"未分类"'

    transcript = _render_transcript(data.get("segments", []), data.get("with_timestamps", True))
    comments = _render_comments(data.get("comments", []))

    repl = {
        "{{TITLE}}": data.get("title", "未命名视频"),
        "{{PLATFORM}}": data.get("platform", ""),
        "{{URL}}": data.get("url", ""),
        "{{TAGS}}": tags_inline,
        "{{TAGS_DISPLAY}}": tags_display,
        "{{VIDEO_DATE}}": str(data.get("video_date", "")),
        "{{ARCHIVE_DATE}}": str(data.get("archive_date", "")),
        "{{DURATION}}": str(data.get("duration", "")),
        "{{SUMMARY}}": data.get("summary", ""),
        "{{PREP}}": data.get("prep", ""),
        "{{TRANSCRIPT}}": transcript,
        "{{COMMENTS}}": comments,
        "{{FILENAME}}": data.get("filename", data.get("title", "未命名视频")),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, str(v))
    return tpl


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: render_markdown.py <json_data_file> [output.md]")
        return 2
    import json

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = render(payload)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(out, encoding="utf-8")
        print(sys.argv[2])
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
