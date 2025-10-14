from pathlib import Path
import os
import json
from typing import List, Dict, Optional

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling_core.types.doc import SectionHeaderItem, TextItem, DocItemLabel

INPUT_DIR = Path("../data/PDFs")
OUTPUT_DIR = Path("./Output")

# Point to your prefetched models if you’ve cached them locally (recommended)
ARTIFACTS_PATH = os.environ.get(
    "DOCLING_ARTIFACTS_PATH",
    str(Path.home() / ".cache" / "docling" / "models")
)

def extract_sections(doc) -> List[Dict]:
    """
    Build a flat list of sections with depth-inferred levels:
      [
        {"heading": "Intro", "level": 1, "text": "..."},
        {"heading": "Background", "level": 2, "text": "..."},
        ...
      ]
    Text is attached to the most recent heading; pre-heading text goes to a "Preamble" level 0.
    """
    sections: List[Dict] = []
    current_idx: Optional[int] = None

    def start_section(title: str, level: int) -> int:
        sections.append({"heading": title, "level": int(level), "text": ""})
        return len(sections) - 1

    def ensure_preamble() -> int:
        nonlocal current_idx
        if current_idx is None:
            current_idx = start_section("Preamble", 0)
        return current_idx

    # Track the smallest depth we ever see for headers to normalize levels to start at 1
    min_hdr_depth: Optional[int] = None
    pending_title: Optional[str] = None

    # First pass: find min header depth (for normalization) and cache title if present
    for element, depth in doc.iterate_items():
        if isinstance(element, SectionHeaderItem):
            min_hdr_depth = depth if (min_hdr_depth is None or depth < min_hdr_depth) else min_hdr_depth
        elif isinstance(element, TextItem) and element.label == DocItemLabel.TITLE:
            # Save a doc title (we'll treat it as a level-1 heading if the doc lacks clear headers before text)
            pending_title = element.text.strip()

    # Second pass: build sections with normalized depth-based levels
    for element, depth in doc.iterate_items():
        if isinstance(element, SectionHeaderItem):
            # Depth-based level (normalize so top-most header depth becomes level 1)
            if min_hdr_depth is None:
                inferred = 1
            else:
                inferred = (depth - min_hdr_depth) + 1
                if inferred < 1:
                    inferred = 1

            # Optional explicit model-provided level (only accept positive ints)
            explicit = element.level if isinstance(getattr(element, "level", None), int) and element.level > 0 else None

            # Choose the more conservative (smaller) level when explicit looks sane
            level = min(explicit, inferred) if explicit else inferred

            current_idx = start_section(element.text.strip(), level)
            continue

        # If there's a TITLE and we haven't started any section yet (and we hit body text),
        # insert the TITLE as a level-1 heading once.
        if isinstance(element, TextItem) and element.label in {DocItemLabel.PARAGRAPH, DocItemLabel.TEXT}:
            if current_idx is None and pending_title:
                current_idx = start_section(pending_title, 1)
                pending_title = None

            idx = current_idx if current_idx is not None else ensure_preamble()
            sections[idx]["text"] += (element.text.rstrip() + "\n\n")

    # Tidy trailing whitespace
    for sec in sections:
        sec["text"] = sec["text"].strip()

    return sections

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Prefer local models to avoid network timeouts
    pipeline_options = PdfPipelineOptions(artifacts_path=ARTIFACTS_PATH)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    pdf_paths = sorted(p for p in INPUT_DIR.glob("**/*.pdf") if p.is_file())
    if not pdf_paths:
        print(f"No PDFs found under: {INPUT_DIR.resolve()}")
        return

    for pdf_path in pdf_paths:
        print(f"Processing: {pdf_path}")
        try:
            result = converter.convert(str(pdf_path))
            sections = extract_sections(result.document)
            out_path = OUTPUT_DIR / (pdf_path.stem + ".json")
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "source_file": str(pdf_path),
                        "num_pages": result.document.num_pages(),
                        "sections": sections,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"⚠️  Failed on {pdf_path.name}: {e}")

if __name__ == "__main__":
    main()