#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Use GPT-4 or GPT-5 to predict headings + hierarchy from pre-extracted features.

Input  (per file):  ../features/XML-OCR/<name>.json
Output (per file):  ./outputs_<model>/<name>.csv
"""

import os
import re
import json
import csv
import time
from typing import List, Dict, Any

import openai
import tiktoken

# ========== CONFIG ==========
MODEL_VERSION = "gpt-5"  # "gpt-4" or "gpt-5"
OPENAI_MODEL = MODEL_VERSION

# Adjust context & chunk size
if MODEL_VERSION == "gpt-5":
    MAX_CONTEXT_TOKENS = 32768
    MAX_ITEMS_PER_CHUNK = 15
    MAX_COMPLETION_TOKENS = 4000
elif MODEL_VERSION == "gpt-4":
    MAX_CONTEXT_TOKENS = 8192
    MAX_COMPLETION_TOKENS = 350
    MAX_ITEMS_PER_CHUNK = 12
else:
    MAX_CONTEXT_TOKENS = 8192
    MAX_ITEMS_PER_CHUNK = 12

OPENAI_TEMPERATURE = 0

SAFETY_BUFFER = 800
MAX_PREV_CONTEXT = 10
INPUT_DIR = "../features/OCR-XML"
OUTPUT_DIR = f"./outputs_{MODEL_VERSION}"

# OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY", "ENTER YOUR OPENAI API KEY HERE")


# ========== TOKEN UTILS ==========
def num_tokens_text(text: str, model: str = OPENAI_MODEL) -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))

def num_tokens_messages(messages: List[Dict[str, str]], model: str = OPENAI_MODEL) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except Exception:
        encoding = tiktoken.get_encoding("cl100k_base")

    tokens_per_message = 3
    tokens_per_name = 1
    n = 0
    for m in messages:
        n += tokens_per_message
        n += len(encoding.encode(m.get("content", "")))
        if m.get("name"):
            n += tokens_per_name
    n += 3
    return n

# ========== PROMPTS ==========
SYSTEM_PROMPT = """
You are a document structure expert. You will receive a list of title candidates extracted from a law textbook,
including their associated content and PDF/XML-derived features. Some candidates may be fragmented or noisy.

TASK:
1) Remove garbage text and duplicates.
2) Predict if each candidate is truly a heading.
3) Assign a realistic hierarchy level (1..10; 1 = top level).
4) Use semantics, content, XML features, and previous headings.
5) Exclude publisher-related or boilerplate items.

OUTPUT:
Return ONLY strict CSV lines:
hierarchy_level,heading,page
- Exactly 3 columns per row, separated by commas
- Heading enclosed in double quotes
- No header row
- No extra text, explanations, or formatting
""".strip()

# After SYSTEM_PROMPT definition
if MODEL_VERSION == "gpt-5":
    SYSTEM_PROMPT += "\n\nDo not spend tokens reasoning silently. Begin output immediately. Limit output to only valid CSV rows."

# ========== BUILD USER MESSAGE ==========
def build_user_message(chunk: List[Dict[str, Any]], prev_context: List[Dict[str, Any]]) -> str:
    prev_rows = []
    for row in prev_context[-MAX_PREV_CONTEXT:]:
        prev_rows.append({
            "hierarchy_level": row.get("hierarchy_level", ""),
            "heading": row.get("heading", ""),
            "page": row.get("page", "")
        })

    def trim_entry(e: Dict[str, Any], max_content_chars: int = 1200) -> Dict[str, Any]:
        out = {"page": e.get("page"), "heading": e.get("heading")}
        content = e.get("content", "")
        if isinstance(content, str) and len(content) > max_content_chars:
            content = content[:max_content_chars] + "…"
        out["content"] = content
        if "features" in e:
            out["features"] = e["features"]
        return out

    compact_chunk = [trim_entry(e) for e in chunk]
    prev_json = json.dumps(prev_rows, separators=(",", ":"))
    chunk_json = json.dumps(compact_chunk, separators=(",", ":"))

    return (
        f"Previously identified headings (for reference only):\n{prev_json}\n\n"
        f"Candidates (analyze and output only valid headings as CSV):\n{chunk_json}"
    )

# ========== CSV PARSING ==========
CSV_LINE_RE = re.compile(r'^\s*"?(\d+)"?,\s*"(.+?)"\s*,\s*"?(\d+)"?\s*$')

def clean_model_output(text: str) -> str:
    text = re.sub(r"^```(?:csv)?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```$", "", text, flags=re.MULTILINE)
    return text.strip()

def extract_csv_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if re.match(r'^\s*"?\d+"?,', line.strip()):
            lines.append(line.strip())
    return "\n".join(lines)

def parse_csv_from_model(output_text: str) -> List[Dict[str, Any]]:
    parsed = []
    for raw_line in output_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = CSV_LINE_RE.match(line)
        if m:
            parsed.append({
                "hierarchy_level": int(m.group(1)),
                "heading": m.group(2),
                "page": int(m.group(3))
            })
    return parsed

# ========== OPENAI CALL ==========
def call_gpt_model(user_message: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    used = num_tokens_messages(messages, model=OPENAI_MODEL)
    if used + MAX_COMPLETION_TOKENS + SAFETY_BUFFER > MAX_CONTEXT_TOKENS:
        raise RuntimeError("Prompt too large even after chunking.")

    kwargs = dict(model=OPENAI_MODEL, messages=messages)
    if MODEL_VERSION == "gpt-5":
        kwargs["max_completion_tokens"] = MAX_COMPLETION_TOKENS
    else:
        kwargs["max_tokens"] = MAX_COMPLETION_TOKENS
        kwargs["temperature"] = OPENAI_TEMPERATURE

   
    resp = openai.chat.completions.create(**kwargs)
    #print("[DEBUG] Full API response:", resp)  # TEMP debugging

    if not resp.choices:
        raise RuntimeError("OpenAI returned no choices.")
    return resp.choices[0].message.content.strip()

# ========== CHUNKING ==========
def dynamic_chunk(items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    chunks = []
    cur = []
    for it in items:
        cur.append(it)
        if len(cur) >= MAX_ITEMS_PER_CHUNK:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks

def shrink_chunk_to_fit(chunk: List[Dict[str, Any]], prev_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    while chunk:
        msg = build_user_message(chunk, prev_context)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": msg}
        ]
        used = num_tokens_messages(messages, model=OPENAI_MODEL)
        if used + MAX_COMPLETION_TOKENS + SAFETY_BUFFER <= MAX_CONTEXT_TOKENS:
            return chunk
        chunk = chunk[:-1]
    return []

# ========== FILE IO ==========
def read_feature_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"Expected a list in {path}")
        return [{
            "page": e.get("page"),
            "heading": e.get("heading", ""),
            "content": e.get("content", ""),
            "features": e.get("features", None)
        } for e in data]

def write_csv(rows: List[Dict[str, Any]], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([r["hierarchy_level"], r["heading"], r["page"]])

# ========== MAIN PIPELINE ==========
def process_file(json_path: str, output_dir: str) -> None:
    fname = os.path.splitext(os.path.basename(json_path))[0]
    out_path = os.path.join(output_dir, f"{fname}.csv")

    items = read_feature_json(json_path)
    chunks = dynamic_chunk(items)

    all_rows: List[Dict[str, Any]] = []
    prev_context: List[Dict[str, Any]] = []

    start = time.time()
    for idx, chunk in enumerate(chunks, 1):
        chunk_fit = shrink_chunk_to_fit(chunk, prev_context)
        if not chunk_fit:
            chunk_fit = shrink_chunk_to_fit(chunk, prev_context=[])
            if not chunk_fit:
                for item in chunk:
                    single_fit = shrink_chunk_to_fit([item], prev_context=[])
                    if not single_fit:
                        print(f"[WARN] Skipping large item in {fname}.")
                        continue
                    umsg = build_user_message(single_fit, [])
                    raw_text = call_gpt_model(umsg)
                    cleaned = extract_csv_lines(clean_model_output(raw_text))
                    rows = parse_csv_from_model(cleaned)
                    if not rows:
                        print(f"[DEBUG] No headings parsed. Raw output:\n{raw_text}")
                    all_rows.extend(rows)
                    prev_context.extend(rows)
                continue

        user_message = build_user_message(chunk_fit, prev_context)
        raw_text = call_gpt_model(user_message)
        cleaned = extract_csv_lines(clean_model_output(raw_text))
        rows = parse_csv_from_model(cleaned)
        if not rows:
            print(f"[DEBUG] No headings parsed in chunk {idx}. Raw output:\n{raw_text}")

        all_rows.extend(rows)
        prev_context.extend(rows)
        print(f"[INFO] {fname}: processed chunk {idx}/{len(chunks)} -> {len(rows)} headings")

    write_csv(all_rows, out_path)
    elapsed = time.time() - start
    print(f"[DONE] Saved: {out_path} ({len(all_rows)} rows) in {elapsed:.2f}s")

def main():
    if not openai.api_key:
        print("[ERROR] OpenAI API key not set.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".json")]
    if not json_files:
        print(f"[WARN] No JSON files found in {INPUT_DIR}")
        return

    total_start = time.time()
    for name in sorted(json_files):
        try:
            process_file(os.path.join(INPUT_DIR, name), OUTPUT_DIR)
        except Exception as e:
            print(f"[ERROR] Failed on {name}: {e}")
    total_elapsed = time.time() - total_start
    print(f"[TOTAL] Finished all files in {total_elapsed:.2f}s")

if __name__ == "__main__":
    main()
