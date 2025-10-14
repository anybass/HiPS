#!/usr/bin/env python3
"""
check_section_levels.py — scan JSON files with a {title, sections[]} schema
and flag any section.level values above a threshold.

Usage:
  python check_section_levels.py /path/to/folder
  python check_section_levels.py /path/to/folder --max-level 1
  python check_section_levels.py /path/to/folder --fail-on-violation
  python check_section_levels.py /path/to/folder -v
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check section.level values in JSON files (schema with 'title' and 'sections').")
    p.add_argument("folder", help="Folder to scan (recursively).")
    p.add_argument("--max-level", type=int, default=1,
                   help="Maximum allowed 'level'. Values greater than this are flagged. Default: 1")
    p.add_argument("--fail-on-violation", action="store_true",
                   help="Exit with code 1 if any violations are found.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print files as they are scanned.")
    return p.parse_args()

def safe_str(x: Any, maxlen: int = 80) -> str:
    s = "" if x is None else str(x)
    s = s.replace("\n", " ").strip()
    return (s[: maxlen - 1] + "…") if len(s) > maxlen else s

def check_file(path: str, max_level: int) -> Tuple[List[str], List[str]]:
    """
    Returns (violations, warnings) for a single file.
    - violations: strings describing levels > max_level
    - warnings: schema issues (missing sections, non-int levels, etc.)
    """
    violations: List[str] = []
    warnings: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        warnings.append(f"{path}: JSON load error: {type(e).__name__}: {e}")
        return violations, warnings

    if not isinstance(data, dict):
        warnings.append(f"{path}: Root is not an object.")
        return violations, warnings

    sections = data.get("sections")
    if not isinstance(sections, list):
        warnings.append(f"{path}: Missing or invalid 'sections' list.")
        return violations, warnings

    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            warnings.append(f"{path}: sections[{i}] is not an object.")
            continue

        level = sec.get("level")
        heading = safe_str(sec.get("heading"))
        if isinstance(level, bool):  # avoid True/False being treated as ints
            warnings.append(f"{path}: sections[{i}] '{heading}': level is boolean ({level}); expected integer.")
            continue
        if not isinstance(level, (int, float)):
            warnings.append(f"{path}: sections[{i}] '{heading}': level is not numeric ({type(level).__name__}).")
            continue

        if level > max_level:
            violations.append(f"{path}: sections[{i}] '{heading}': level={level} > {max_level}")

    return violations, warnings

def main() -> int:
    args = parse_args()
    folder = os.path.abspath(args.folder)

    if not os.path.isdir(folder):
        print(f"Error: '{folder}' is not a directory.", file=sys.stderr)
        return 2

    total_files = 0
    json_files = 0
    all_violations: List[str] = []
    all_warnings: List[str] = []

    for root, _, files in os.walk(folder):
        for name in files:
            total_files += 1
            if not name.lower().endswith(".json"):
                continue
            json_files += 1
            path = os.path.join(root, name)
            if args.verbose:
                print(f"Scanning {path}...")
            violations, warnings = check_file(path, args.max_level)
            all_violations.extend(violations)
            all_warnings.extend(warnings)

    print(f"\nScanned files: {total_files} (JSON: {json_files})")

    if all_warnings:
        print(f"\nSchema warnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  - {w}")

    if all_violations:
        print(f"\nViolations (level > {args.max_level}) found: {len(all_violations)}")
        for v in all_violations:
            print(f"  - {v}")
        return 1 if args.fail_on_violation else 0
    else:
        print(f"\nNo 'level' values above {args.max_level} were found. ✅")
        return 0

if __name__ == "__main__":
    sys.exit(main())
