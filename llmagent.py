#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Feb  2 22:10:11 2025

@author: sabine
"""

import xml.etree.ElementTree as ET
from collections import Counter
from langchain.llms import LlamaCpp


# Load the model (already in your setup)
def load_model(model_type="llama", model_path=None):
    if model_type == "llama":
        default_model_path = "./llama3-70b-gguf/Llama-3.3-70B-Instruct-Q5_K_M.gguf"
    elif model_type == "mistral":
        default_model_path = "./Mistral-Large-Instruct-2411-IQ4_XS/Mistral-Large-Instruct-2411-IQ4_XS-00001-of-00002.gguf"
    else:
        raise ValueError(f"Unknown model type: {model_type}. Use 'llama' or 'mistral'.")
    
    model_path = model_path or default_model_path
    print(f"[INFO] Loading {model_type} model from {model_path}...")
    
    llm = LlamaCpp(
        model_path=model_path,
        temperature=0,
        max_tokens=2048,
        n_ctx=4096,
        n_gpu_layers=5
    )
    return llm


# Extract text with metadata
def extract_text_with_metadata(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    font_sizes = {}
    extracted_data = []

    for font_spec in root.iter("fontspec"):
        font_id = font_spec.attrib.get("id")
        font_size = float(font_spec.attrib.get("size"))
        font_sizes[font_id] = font_size

    current_page = 1
    current_entry = None

    for elem in root.iter():
        if elem.tag == "page":
            current_page = int(elem.attrib.get("number", current_page))
        elif elem.tag == "text":
            text = elem.text.strip() if elem.text else ""
            font_id = elem.attrib.get("font")
            bold = "bold" in elem.attrib.get("type", "").lower()
            italic = "italic" in elem.attrib.get("type", "").lower()
            top = int(elem.attrib.get("top", 0))
            left = int(elem.attrib.get("left", 0))

            if text and font_id in font_sizes:
                new_entry = {
                    "text": text,
                    "font_size": font_sizes[font_id],
                    "bold": bold,
                    "italic": italic,
                    "page_number": current_page,
                    "top": top,
                    "left": left
                }

                if (current_entry and
                    current_entry["font_size"] == new_entry["font_size"] and
                    current_entry["bold"] == new_entry["bold"] and
                    current_entry["italic"] == new_entry["italic"] and
                    current_entry["page_number"] == new_entry["page_number"] and
                    abs(current_entry["top"] - new_entry["top"]) < 5):
                    current_entry["text"] += " " + new_entry["text"]
                else:
                    if current_entry:
                        extracted_data.append(current_entry)
                    current_entry = new_entry

    if current_entry:
        extracted_data.append(current_entry)

    return extracted_data


# LLM-based title refinement
def refine_and_merge_titles_with_llm(llm, title_candidates):
    """
    Use an LLM to refine and merge closely related title candidates into complete section titles.
    """
    title_texts = [entry["text"] for entry in title_candidates]

    prompt = (
        "You are a document structure expert. The following is a list of section title candidates extracted "
        "from a textbook. Some of them are fragmented or incomplete and need to be merged. Please merge related titles "
        "where appropriate and output a clean list of section titles:\n\n"
        f"Title candidates: {title_texts}\n\n"
        "Merged and clean section titles:"
    )

    response = llm.invoke(prompt)
    return [title.strip() for title in response.split("\n") if title.strip()]


# LLM-based hierarchy assignment
def assign_hierarchy_with_llm(llm, refined_titles):
    """
    Use the LLM to assign hierarchy levels (e.g., chapter, section, sub-section) to each refined title.
    """
    prompt = (
        "You are a document structure expert. Below is a list of section titles from a textbook. "
        "Assign each title a hierarchy level: 1 for major chapters, 2 for sections, 3 for subsections, "
        "and so on. Provide the title followed by its hierarchy level in this format:\n"
        "Title: <title> | Level: <hierarchy level>\n\n"
        f"Section titles: {refined_titles}\n\n"
        "Output:"
    )

    response = llm.invoke(prompt)
    return [
        {"title": line.split("|")[0].strip().replace("Title: ", ""),
         "hierarchy_level": int(line.split("|")[1].strip().replace("Level: ", ""))}
        for line in response.split("\n") if line.strip()
    ]


# Main function to extract, refine, and assign hierarchy
def detect_and_hierarchy_assign(xml_path, model_type):
    extracted_data = extract_text_with_metadata(xml_path)
    
    # Detect potential title candidates based on formatting cues
    title_candidates = [
        entry for entry in extracted_data if entry["font_size"] > 14 or entry["bold"] or entry["italic"]
    ]

    # Load the LLM model
    llm = load_model(model_type)

    # Step 1: Refine and merge title candidates using the LLM
    refined_titles = refine_and_merge_titles_with_llm(llm, title_candidates)

    # Step 2: Assign hierarchy levels to refined titles using the LLM
    titles_with_hierarchy = assign_hierarchy_with_llm(llm, refined_titles)

    # Output the final structured list
    return titles_with_hierarchy


# Example Run
xml_path = "./xml/access-to-justice-and-legal-empowerment-making-the-poor-central-in-legal-development-co-operati.xml"
model_type="mistral"
titles_with_hierarchy = detect_and_hierarchy_assign(xml_path, model_type)

# Print results
for title in titles_with_hierarchy:
    title_text = title.get('text') or title.get('title')
    if title_text and 'hierarchy_level' in title:
        print(f"Title: {title_text}\nLevel: {title['hierarchy_level']}\nPage: {title.get('page_number', 'Unknown')}\n")
    else:
        print("[WARNING] Skipping title due to missing keys or values:", title)
