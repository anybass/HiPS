#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert PDFs to Markdown with Marker, then build a structural outline by parsing
Markdown headings (#, ##, ###, ...). Adds level normalization so gaps like 2→4
become 3, and the first heading always starts at level 1.

Outputs per PDF:
  <name>.md               -> Marker-rendered Markdown
  <name>.outline.json     -> Nested JSON tree (normalized levels)
  <name>.structured.md    -> Markdown rebuilt from that tree
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# Install with: pip install "marker-pdf[full]"
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.config.parser import ConfigParser

INPUT_DIR = Path("../data/PDFs")
OUTPUT_DIR = Path("./Markdown")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Markdown parsing ----------------

_ATX = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)(\s+#+\s*)?$")
_SETEXT_H1 = re.compile(r"^=+\s*$")
_SETEXT_H2 = re.compile(r"^-+\s*$")

def _strip_trailing_code_fence_ticks(line: str) -> str:
    return re.sub(r"\s*`{3,}\s*$", "", line)

def parse_markdown_outline(md: str) -> Dict[str, Any]:
    """
    Build a nested tree by scanning Markdown headings and normalizing their levels.
    - Supports ATX (#..######) and Setext (===, ---)
    - Ignores headings inside fenced code blocks
    - Normalization:
        * First heading becomes level 1 (base shift)
        * Any jump > +1 is compressed to +1 (e.g., 2→4 becomes 3)
    Returns: {title, level, content[], children[]}
    """
    root = {"title": "Document", "level": 0, "content": [], "children": []}
    stack: List[Dict[str, Any]] = [root]

    lines = md.splitlines()
    in_code_fence = False
    fence_delim: Optional[str] = None
    pending_para: List[str] = []
    prev_line: Optional[str] = None

    base_offset: Optional[int] = None  # first heading's raw_level - 1

    def flush_content():
        nonlocal pending_para
        if pending_para:
            text = "\n".join(pending_para).strip()
            if text:
                stack[-1].setdefault("content", []).append(text)
            pending_para = []

    def normalize_level(raw_level: int) -> int:
        """
        - Shift so first heading is 1
        - Compress jumps: new_level <= stack_top+1
        """
        nonlocal base_offset
        if base_offset is None:
            base_offset = max(raw_level - 1, 0)
        lvl = max(1, raw_level - base_offset)

        # compress gap relative to current stack top
        top_level = stack[-1]["level"]
        if lvl > top_level + 1:
            lvl = top_level + 1
        return min(lvl, 6)

    def push_heading(raw_level: int, title: str):
        level = normalize_level(raw_level)
        node = {"title": title.strip(), "level": level, "content": [], "children": []}
        # pop until parent has smaller level
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Fence open/close (``` or ~~~)
        m_fence = re.match(r"^(```+|~~~+)", line)
        if m_fence:
            ticks = m_fence.group(1)
            if not in_code_fence:
                in_code_fence = True
                fence_delim = ticks[0]
            elif in_code_fence and fence_delim == ticks[0]:
                in_code_fence = False
                fence_delim = None
            pending_para.append(line)
            prev_line = line
            i += 1
            continue

        if in_code_fence:
            pending_para.append(line)
            prev_line = line
            i += 1
            continue

        # ATX heading
        m_atx = _ATX.match(_strip_trailing_code_fence_ticks(line))
        if m_atx:
            flush_content()
            raw_level = len(m_atx.group("hashes"))
            title = m_atx.group("title").strip()
            push_heading(raw_level, title)
            prev_line = line
            i += 1
            continue

        # Setext heading (use previous non-empty, non-ATX line as title)
        if prev_line is not None and prev_line.strip() and not prev_line.lstrip().startswith("#"):
            if _SETEXT_H1.match(line):
                flush_content()
                push_heading(1, prev_line.strip())
                prev_line = line
                i += 1
                continue
            if _SETEXT_H2.match(line):
                flush_content()
                push_heading(2, prev_line.strip())
                prev_line = line
                i += 1
                continue

        # Normal content
        pending_para.append(line)
        prev_line = line
        i += 1

    flush_content()
    return root

def outline_to_markdown(node: Dict[str, Any]) -> str:
    """Render the outline tree back to Markdown using (normalized) heading levels."""
    out: List[str] = []

    def walk(n: Dict[str, Any]):
        if n["level"] > 0:
            out.append("#" * n["level"] + " " + n["title"])
        for chunk in n.get("content", []):
            out.append(chunk)
        for c in n.get("children", []):
            walk(c)

    walk(node)
    text = "\n\n".join(out).strip()
    return (text + "\n") if text else ""

# ---------------- Marker conversion ----------------

def convert_pdf_to_marker_markdown(pdf_path: Path, converter_md: PdfConverter) -> str:
    rendered = converter_md(str(pdf_path))
    md = getattr(rendered, "markdown", "")
    if not isinstance(md, str):
        md = str(md or "")
    return md

def process_pdf(pdf_path: Path, converter_md: PdfConverter):
    marker_md = convert_pdf_to_marker_markdown(pdf_path, converter_md)
    outline = parse_markdown_outline(marker_md)
    structured_md = outline_to_markdown(outline)

    stem = pdf_path.stem
    (OUTPUT_DIR / f"{stem}.md").write_text(marker_md, encoding="utf-8")
    (OUTPUT_DIR / f"{stem}.outline.json").write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{stem}.structured.md").write_text(structured_md, encoding="utf-8")

def main():
    if not INPUT_DIR.exists():
        raise SystemExit(f"Input folder not found: {INPUT_DIR.resolve()}")

    cfg_md = ConfigParser({"output_format": "markdown"}).generate_config_dict()
    converter_md = PdfConverter(config=cfg_md, artifact_dict=create_model_dict())

    pdfs = sorted([p for p in INPUT_DIR.glob("**/*.pdf") if p.is_file()])
    if not pdfs:
        print(f"No PDFs found in {INPUT_DIR.resolve()}")
        return

    print(f"Found {len(pdfs)} PDFs in {INPUT_DIR.resolve()}")
    for p in pdfs:
        try:
            print(f"Converting: {p.name}")
            process_pdf(p, converter_md)
        except Exception as e:
            print(f"[WARN] Failed on {p}: {e}")

    print(f"Done. Output written to: {OUTPUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
