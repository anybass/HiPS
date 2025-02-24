#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Feb 17 18:15:03 2025

@author: sabine
"""

import os
import xml.etree.ElementTree as ET
import glob
import openai
import json
from collections import Counter
import chardet
import csv
import io
from fuzzywuzzy import fuzz
import tiktoken
from tqdm import tqdm


# OpenAI API Configuration
openai.api_key = "INSERT_OPENAI_API_KEY_HERE"  # Replace with your actual OpenAI API key

# Ensure output directory exists
os.makedirs("./title_candidates", exist_ok=True)

def count_tokens(text, model="gpt-4"):
    """Uses tiktoken to count tokens accurately."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))

def extract_titles(response_text):
    titles = []
    
    reader = csv.reader(io.StringIO(response_text), quotechar='"', skipinitialspace=True)
    
    for row in reader:
        if len(row) != 3:
            print(f"[WARNING] Skipping malformed row: {row}")
            continue  # Skip malformed rows
        
        hierarchy_level, heading, page = row
        
        # Strip whitespace
        hierarchy_level = hierarchy_level.strip()
        heading = heading.strip()
        page = page.strip()
        
        # Ensure page is always set as an integer, defaulting to None if invalid
        try:
            page = int(page)
        except ValueError:
            print(f"[WARNING] Invalid page number in row: {row}")
            page = None

        titles.append({"hierarchy_level": hierarchy_level, "heading": heading, "page": page})
    
    return titles

# Function to detect encoding of a file
def detect_encoding(file_path):
    with open(file_path, 'rb') as file:
        detector = chardet.universaldetector.UniversalDetector()
        for line in file:
            detector.feed(line)
            if detector.done:
                break
        detector.close()
    return detector.result['encoding']

# Extract text with metadata and determine baseline font size
def extract_text_with_metadata(xml_path):
    enc=detect_encoding(xml_path)
    if enc!="utf-8":
        print("Encoding not utf8:")
        print(enc)
        input()
    tree = ET.parse(xml_path)
    root = tree.getroot()
    font_sizes = {}
    extracted_data = []

    for font_spec in root.iter("fontspec"):
        font_id = font_spec.attrib.get("id")
        font_size = float(font_spec.attrib.get("size"))
        font_sizes[font_id] = font_size
        

    font_usage = Counter()
    font_ids= Counter()
    current_page = 1

    for elem in root.iter():
        if elem.tag == "page":
            current_page = int(elem.attrib.get("number", current_page))
        elif elem.tag == "text":
            text = "".join(elem.itertext()).strip()
            font_id = elem.attrib.get("font")
            bold = any(child.tag == "b" for child in elem)
            italic = any(child.tag == "i" for child in elem)
            top = int(elem.attrib.get("top", 0))
            left = int(elem.attrib.get("left", 0))

            if text and font_id in font_sizes:
                font_usage[font_sizes[font_id]] += 1
                font_ids[font_id]+=1
                extracted_data.append({
                    "text": text,
                    "font_id": font_id,
                    "font_size": font_sizes[font_id],
                    "bold": bold,
                    "italic": italic,
                    "page": current_page,
                    "top": top,
                    "left": left
                })

    most_common_fonts = font_usage.most_common()
    most_common_font_ids= font_ids.most_common()
    #for debugging
    print(most_common_fonts)
    print(most_common_font_ids)
   
    baseline_fonts = [font[0] for font in most_common_fonts if font[1] > 0.5 * most_common_fonts[0][1]]
    
    return extracted_data, baseline_fonts, most_common_fonts, most_common_font_ids

def save_text_as_csv(data, filename, folder="./title_candidates"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for row in data:
                if isinstance(row, dict) and "hierarchy_level" in row and "heading" in row and "page" in row:
                    writer.writerow([row["hierarchy_level"], row["heading"], row["page"]])
        print(f"[INFO] CSV saved: {path}")
    except Exception as e:
        print(f"[ERROR] Failed to save CSV: {e}")

# Save text output (for debugging and logs)
def save_text(data, filename, folder="./title_candidates"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2) if isinstance(data, (dict, list)) else data)
        print(f"[INFO] Text saved: {path}")
    except Exception as e:
        print(f"[ERROR] Failed to save text: {e}")
        
def limit_previous_titles_by_level(previous_batches):
    """Keeps only the most recent title for each hierarchy level."""
    last_titles = {}
    for title_entry in reversed(previous_batches):
        #print("title_entry")
        #print(title_entry)
        level = title_entry.get("hierarchy_level", 1)  # Default to level 1 if missing
        if level not in last_titles:
            last_titles[level] = title_entry
    return list(last_titles.values())

# Process title candidates and send them to GPT-4
def refine_titles_and_assign_hierarchy(title_candidates, xml_filename, max_context=8192, max_response_tokens=1000, model="gpt-4"):
    """Refines titles in batches, considering previous context and GPT-4 token limits."""
    refined_titles = []
    batch = []
    token_count = 0
    
    system_prompt = """
    You are a document structure expert. The following is a list of section title candidates extracted 
    from a textbook. Some are fragmented or contain noise (e.g., special characters).

    **TASK:**
    1. Merge related titles into one coherent section title.
    2. Remove garbage text (if it's not part of a title) or duplicate entries (e.g., if a title may also appear in a header).
    3. Assign a realistic hierarchy level based on **formatting cues (font size, bold, indentation)**.
    4. Use a reasonable depth (typically 2-3 levels, up to 10 if necessary).
    5. **Return output in csv format: hierarchy_level, heading, page**
    
    Example input: [{'text': 'Introduction,'font_size':16, 'bold':True, 'italic':False, 'page':3,'top':70 , 'left':75},
                    {'text':'Facts','font_size':14, 'bold':False, 'italic':True,'page':5 , 'top':140 , 'left':75},
                    {'text':'Reasoning','font_size':14, 'bold':False, 'italic':True ,'page':8 , 'top':300 , 'left':75}]
    
    Example output: 
    1,"Introduction",3
    2,"Facts",5
    2,"Reasoning",8
    
    Do NOT explain the output. Please ensure:
    - All headings are enclosed in **double quotes** (""), even if they contain no commas.
    - Do not insert extra line breaks inside headings.
    - Ensure exactly **3 columns per row**: `hierarchy_level, heading, page`.
    - Do not duplicate entries unless they appear on different pages.
    
    Return a valid **CSV file without header**.
    """
    
    system_prompt_tokens = count_tokens(system_prompt, model)
    
    system_prompt_tokens = count_tokens(system_prompt, model)

    for entry in tqdm(title_candidates, desc="Processing title candidates"):
        title_text = str(entry)
        title_tokens = count_tokens(title_text, model)
        
        if refined_titles: 
            previous_titles = limit_previous_titles_by_level(refined_titles)
        else: 
            previous_titles=[]
        context_tokens = sum(count_tokens(str(t), model) for t in previous_titles)
        
        total_tokens = system_prompt_tokens + context_tokens + token_count + title_tokens + max_response_tokens
        if total_tokens > max_context - 1800:
            print(f"[INFO] Processing batch (Tokens Used: {token_count}/{max_context})")
            processed_batch = process_title_batch(batch, previous_titles, xml_filename, system_prompt, model)
            refined_titles.extend([row for row in processed_batch if isinstance(row, dict) and "hierarchy_level" in row and "heading" in row and "page" in row])
        
            
            batch = []
            token_count = 0
        
        batch.append(entry)
        token_count += title_tokens
    
    if batch:
        print(f"[INFO] Processing final batch (Tokens Used: {token_count}/{max_context})")
        processed_batch = process_title_batch(batch, limit_previous_titles_by_level(refined_titles), xml_filename, system_prompt, model)
        refined_titles.extend([row for row in processed_batch if isinstance(row, dict) and "hierarchy_level" in row and "heading" in row and "page" in row])
        
    
    
    save_text_as_csv(refined_titles, f"titles_{xml_filename}.csv", folder="./title_candidates")
    
    return refined_titles

   

# Send a batch to GPT-4
def process_title_batch(batch, previous_titles, xml_filename, system_prompt, model="gpt-4"):
    """Sends a batch of title candidates to GPT-4 for processing."""
    prompt_content = system_prompt + "\n\nPrevious Context:\n" + json.dumps(previous_titles, indent=2) + "\n\nTitle Candidates:\n" + json.dumps(batch, indent=2)
    
    messages = [
        {"role": "system", "content": "You are a document structure expert. Analyze the provided title candidates."},
        {"role": "user", "content": prompt_content}
    ]
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0,
            max_tokens=1000
        )
        if response.choices:
            response_text = response.choices[0].message.content.strip()
            #print(response_text)
        else:
            raise ValueError("GPT-4 returned no choices in the response.")
        try:
            return extract_titles(response_text)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON decoding failed: {e}")
            save_text(f"JSON decoding failed: {e} Response: {response_text}", f"error_titles_{xml_filename}.txt", folder="./title_candidates")
            return []
    except Exception as e:
        print(f"[ERROR] GPT-4 Invocation Failed: {e}")
        save_text(f"GPT-4 invocation failed: {e}\n\n {prompt_content}", f"error_titles_{xml_filename}.txt", folder="./title_candidates")
        return []


# Process Textbook Structure
def process_textbook_structure(xml_path):
    extracted_data, baseline_fonts, most_common_font_size, most_common_font_id = extract_text_with_metadata(xml_path)
    xml_filename = os.path.basename(xml_path).replace(".xml", "")
    print(baseline_fonts)
    #filtered_fonts= [font_size for font_size, count in most_common_font_size if count <= 300]
    #title_candidates = [
    #    entry for entry in extracted_data if entry["font_size"] in filtered_fonts and (entry["font_size"] > max(baseline_fonts) or entry["bold"] or entry["italic"])
    #]
    #if not title_candidates and most_common_font_id:
     #   print(f"[INFO] No title candidates found in {xml_path}. Retrying using filtered font ID logic...")
    filtered_font_ids = [font_id for font_id, count in most_common_font_id if count <= 220]
    title_candidates = [
        entry for entry in extracted_data if entry["font_id"] in filtered_font_ids
    ]
    print(len(title_candidates))
       
  
    if not title_candidates:
        print(most_common_font_id)
        print(f"[ERROR] No title candidates found in {xml_path}. Skipping...")
        input()
        save_text("No title candidates found.", f"error_{xml_filename}.txt")
        return

    refined_titles = refine_titles_and_assign_hierarchy(title_candidates, xml_filename)

    if not refined_titles:
        print(f"[ERROR] No valid titles extracted from GPT-4 for {xml_filename}.")
        return


# Process all XML files in the folder
xml_folder = "./xml/"
xml_files = sorted(glob.glob(os.path.join(xml_folder, "*.xml")))[19:23]

for xml_file in xml_files:
    print(f"[INFO] Processing: {xml_file}")
    process_textbook_structure(xml_file)
