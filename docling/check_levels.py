#!/usr/bin/env python3
"""
check_levels.py — scan JSON files for `level` values > 1.

Usage:
  python check_levels.py /path/to/folder
  python check_levels.py /path/to/folder --fail-on-violation
  python check_levels.py /path/to/folder --max-level 1
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Any, List, Tuple

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Find 'level' values above a threshold in JSON files.")
    p.add_argument("folder", help="Folder to scan (searched recursively).")
    p.add_argument("--max-level", type=int, default=1,
                   help="Maximum allowed level value. Anything greater is flagged. Default: 1")
    p.add_argument("--fail-on-violation", action="store_true",
                   help="Exit with code 1 if any violations are found.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print files as they are scanned.")
    return p.parse_args()

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def scan_obj(obj: Any, path: str = "$") -> List[Tuple[str, Any]]:
    """
    Recursively scan a Python object parsed from JSON.
    Return list of (json_path, value) for any key named 'level' (any nesting).
    """
    hits: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}"
            if k == "level":
                hits.append((child_path, v))
            hits.extend(scan_obj(v, child_path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child_path = f"{path}[{i}]"
            hits.extend(scan_obj(v, child_path))
    # primitives -> nothing to do
    return hits

def main() -> int:
    args = parse_args()
    folder = os.path.abspath(args.folder)

    if not os.path.isdir(folder):
        print(f"Error: '{folder}' is not a directory.", file=sys.stderr)
        return 2

    total_files = 0
    json_files = 0
    violations: List[Tuple[str, str, Any]] = []  # (file, json_path, value)
    errors: List[Tuple[str, str]] = []  # (file, error_message)

    for root, _, files in os.walk(folder):
        for name in files:
            total_files += 1
            if not name.lower().endswith(".json"):
                continue
            json_files += 1
            fpath = os.path.join(root, name)
            if args.verbose:
                print(f"Scanning {fpath}...")
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                errors.append((fpath, f"{type(e).__name__}: {e}"))
                continue

            for json_path, value in scan_obj(data):
                if is_number(value) and value > args.max_level:
                    violations.append((fpath, json_path, value))

    # Output
    print(f"\nScanned files: {total_files} (JSON: {json_files})")
    if errors:
        print(f"\nFiles with errors ({len(errors)}):")
        for f, msg in errors:
            print(f"  - {f}\n      -> {msg}")

    if violations:
        print(f"\nViolations (level > {args.max_level}) found: {len(violations)}")
        # Group by file for readability
        by_file: dict[str, List[Tuple[str, Any]]] = {}
        for f, path, val in violations:
            by_file.setdefault(f, []).append((path, val))
        for f, items in by_file.items():
            print(f"\n  {f}")
            for path, val in items:
                print(f"    - {path} = {val}")
        result = 1 if args.fail_on_violation else 0
    else:
        print(f"\nNo 'level' values above {args.max_level} were found. ✅")
        result = 0

    return result

if __name__ == "__main__":
    sys.exit(main())
