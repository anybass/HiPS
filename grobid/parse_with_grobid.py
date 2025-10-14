#!/usr/bin/env python3
"""
Batch structural PDF parsing with GROBID.
Input PDFs:  ../data/PDFs
Outputs:      ./Output/tei_xml/*.tei.xml and ./Output/sections_json/*.json

Usage:
    python grobid_structural_parse.py
"""

import os
import json
import time
import glob
import pathlib
import logging
from typing import List, Dict, Optional

import requests
from lxml import etree
from tqdm import tqdm

# ------------ Config ------------
GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")  # change if needed
INPUT_DIR = "../data/PDFs"
OUTPUT_DIR = "./Output"
TEI_DIR = os.path.join(OUTPUT_DIR, "tei_xml")
JSON_DIR = os.path.join(OUTPUT_DIR, "sections_json")

# GROBID request options (tweak to taste)
GROBID_ENDPOINT = f"{GROBID_URL.rstrip('/')}/api/processFulltextDocument"
GROBID_PARAMS = {
    "consolidateHeader": "1",   # better metadata
    "consolidateCitations": "0",
    "includeRawCitations": "0",
    "includeRawAffiliations": "0",
    "segmentSentences": "0",
    "teicolors": "0"
}
REQUEST_TIMEOUT = 300  # seconds
RETRY_ATTEMPTS = 3
RETRY_SLEEP = 5  # seconds

# TEI namespace
NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# ------------ Helpers ------------

def ensure_dirs():
    os.makedirs(TEI_DIR, exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)

def list_pdfs(folder: str) -> List[str]:
    return sorted(glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True))

def call_grobid(pdf_path: str) -> Optional[str]:
    """
    Sends a PDF to GROBID and returns TEI XML text, or None on failure.
    Retries a few times if the server is busy.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with open(pdf_path, "rb") as f:
                files = {"input": (os.path.basename(pdf_path), f, "application/pdf")}
                resp = requests.post(GROBID_ENDPOINT, params=GROBID_PARAMS, files=files, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200 and resp.text.strip():
                return resp.text
            else:
                logging.warning("GROBID returned status %s for %s (attempt %d): %s",
                                resp.status_code, pdf_path, attempt, resp.text[:200])
        except requests.RequestException as e:
            logging.warning("Request error for %s (attempt %d): %s", pdf_path, attempt, e)
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_SLEEP)
    return None

def get_text_excluding_subdivs(div_el: etree._Element) -> str:
    """
    Return the text that belongs to the current <div>, excluding the text contained in nested <div>s.
    We collect text from direct children that are NOT <div>, e.g., <p>, <figure>, <list>, etc.
    """
    chunks = []
    for child in div_el:
        # Skip nested sections
        if child.tag == f"{{{NS['tei']}}}div":
            continue
        # Gather textual content of this immediate child
        txt = " ".join(" ".join(t.strip().split()) for t in child.itertext())
        if txt:
            chunks.append(txt)
    # Also include tail text directly on the div (rare, but safe)
    direct_text = (div_el.text or "").strip()
    if direct_text:
        chunks.insert(0, direct_text)
    # Normalize whitespace
    return " ".join(" ".join(c.split()) for c in chunks).strip()

def extract_sections_from_tei(tei_xml: str) -> Dict:
    """
    Parse TEI and extract a linear list of sections with heading, level, and text.
    Levels start at 1 for <body>/<div> direct children, then 2 for their <div> children, etc.
    """
    root = etree.fromstring(tei_xml.encode("utf-8"))
    # title (optional)
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)
    doc_title = title_el.text.strip() if (title_el is not None and title_el.text) else None

    body = root.find(".//tei:text/tei:body", namespaces=NS)
    sections: List[Dict] = []

    def walk(div_el: etree._Element, level: int):
        # Heading: prefer <head>, else @type/@n, else fallback
        head_el = div_el.find("./tei:head", namespaces=NS)
        heading = None
        if head_el is not None:
            heading = " ".join(" ".join(t.strip().split()) for t in head_el.itertext()).strip() or None
        if not heading:
            # Sometimes structure uses @type or @n if head is missing
            heading = div_el.get("type") or div_el.get("n") or "(untitled section)"

        # Section text excluding nested <div>s
        body_text = get_text_excluding_subdivs(div_el)

        sections.append({
            "heading": heading,
            "level": level,
            "text": body_text
        })

        # Recurse into child divs
        for child_div in div_el.findall("./tei:div", namespaces=NS):
            walk(child_div, level + 1)

    if body is not None:
        for top_div in body.findall("./tei:div", namespaces=NS):
            walk(top_div, level=1)

    return {
        "title": doc_title,
        "sections": sections
    }

def save_text(path: str, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def save_json(path: str, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ------------ Main ------------

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ensure_dirs()

    pdfs = list_pdfs(INPUT_DIR)
    if not pdfs:
        logging.error("No PDFs found in %s", INPUT_DIR)
        return

    successes, failures = 0, 0
    for pdf_path in tqdm(pdfs, desc="Processing PDFs"):
        try:
            tei_xml = call_grobid(pdf_path)
            if not tei_xml:
                failures += 1
                continue

            base = pathlib.Path(pdf_path).with_suffix("").name
            tei_out = os.path.join(TEI_DIR, base + ".tei.xml")
            json_out = os.path.join(JSON_DIR, base + ".json")

            save_text(tei_out, tei_xml)

            structured = extract_sections_from_tei(tei_xml)
            structured["source_pdf"] = os.path.abspath(pdf_path)
            save_json(json_out, structured)

            successes += 1
        except Exception as e:
            logging.exception("Failed on %s: %s", pdf_path, e)
            failures += 1

    logging.info("Done. %d succeeded, %d failed.", successes, failures)
    logging.info("TEI saved to:   %s", os.path.abspath(TEI_DIR))
    logging.info("JSON saved to:  %s", os.path.abspath(JSON_DIR))

if __name__ == "__main__":
    main()