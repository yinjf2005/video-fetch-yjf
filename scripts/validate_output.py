#!/usr/bin/env python3
"""Layer 4.2: validate rendered Markdown (formatting & required fields)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List


REQUIRED_FIELDS = ["标题", "来源", "标签", "视频发布日期", "内容存档日期"]
ISSUES: List[str] = []


def check(md: str) -> List[str]:
    issues: List[str] = []

    # required fields present in the 基本信息 table
    for f in REQUIRED_FIELDS:
        if f not in md:
            issues.append(f"缺少必填字段：{f}")

    # heading hierarchy: no skip from # to ### without ##
    levels = [len(m.group(0)) for m in re.finditer(r"^#{1,6} ", md, re.MULTILINE)]
    for a, b in zip(levels, levels[1:]):
        if b > a + 1:
            issues.append(f"标题层级跳跃：从 H{a} 直接到 H{b}")

    # table column consistency
    for tbl in re.findall(r"(\|.*\|\n\|[\s:|-]+\|\n(?:\|.*\|\n?)*)", md):
        rows = [r for r in tbl.strip().splitlines() if r.strip().startswith("|")]
        col_counts = {r.count("|") for r in rows}
        if len(col_counts) > 1:
            issues.append("表格列数不一致")

    # code fence balance
    fences = md.count("```")
    if fences % 2 != 0:
        issues.append("代码块未闭合")

    # no leftover template tokens
    if re.search(r"\{\{[A-Z_]+\}\}", md):
        issues.append("存在未替换的模板占位符")

    return issues


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_output.py <note.md>")
        return 2
    md = Path(sys.argv[1]).read_text(encoding="utf-8")
    issues = check(md)
    if issues:
        print("VALIDATION FAILED:")
        for i in issues:
            print(" -", i)
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
