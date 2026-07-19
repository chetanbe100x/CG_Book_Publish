from __future__ import annotations

import re
from docx import Document

def relocate_chapter(doc: Document, chapter_match_pattern: str, insert_before_pattern: str) -> None:
    paragraphs = doc.paragraphs
    chapter_p_indices = []
    
    for idx, p in enumerate(paragraphs):
        text = p.text.strip()
        if not text:
            continue
        norm = re.sub(r"\s+", " ", text).strip().replace("–", "-").replace("—", "-")
        if norm.startswith("अध्याय") or norm.lower().startswith("chapter") or "भाग-ब" in norm or "part b" in norm.lower():
            chapter_p_indices.append((idx, p))
            
    start_p_idx = -1
    end_p_idx = -1
    
    for i, (p_idx, p) in enumerate(chapter_p_indices):
        text = p.text.strip()
        if re.search(chapter_match_pattern, text, re.IGNORECASE):
            start_p_idx = p_idx
            if i + 1 < len(chapter_p_indices):
                end_p_idx = chapter_p_indices[i + 1][0]
            break
            
    if start_p_idx == -1:
        print(f"[chapter_structure] Could not find chapter matching pattern: '{chapter_match_pattern}'")
        return
        
    insert_before_p_idx = -1
    for idx, p in enumerate(paragraphs):
        text = p.text.strip()
        if re.search(insert_before_pattern, text, re.IGNORECASE):
            insert_before_p_idx = idx
            break
            
    if insert_before_p_idx == -1:
        print(f"[chapter_structure] Could not find insertion point matching pattern: '{insert_before_pattern}'")
        return
        
    body = doc.element.body
    body_children = list(body.iterchildren())
    
    start_el_xml = paragraphs[start_p_idx]._p
    end_el_xml = paragraphs[end_p_idx]._p if end_p_idx != -1 else None
    insert_before_el_xml = paragraphs[insert_before_p_idx]._p
    
    idx_start = body_children.index(start_el_xml)
    idx_end = body_children.index(end_el_xml) if end_el_xml is not None else len(body_children)
    
    ch_elements = body_children[idx_start:idx_end]
    
    for el in ch_elements:
        body.remove(el)
        
    body_children_new = list(body.iterchildren())
    insert_pos = body_children_new.index(insert_before_el_xml)
    
    for el in ch_elements:
        body.insert(insert_pos, el)
        insert_pos += 1
        
    safe_match = chapter_match_pattern.encode('ascii', errors='backslashreplace').decode('ascii')
    safe_insert = insert_before_pattern.encode('ascii', errors='backslashreplace').decode('ascii')
    print(f"[chapter_structure] Relocated chapter matching '{safe_match}' before '{safe_insert}'.")

def unify_headings(doc: Document, heading_unification_config: list[dict]) -> None:
    paragraphs = doc.paragraphs
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        text = p.text.strip()
        if not text:
            i += 1
            continue
            
        norm = re.sub(r"\s+", " ", text).strip().replace("–", "-").replace("—", "-")
        is_heading = (norm.startswith("अध्याय") or 
                      norm.lower().startswith("chapter") or 
                      "भाग-ब" in norm or 
                      "part b" in norm.lower())
        if not is_heading:
            i += 1
            continue
            
        for cfg in heading_unification_config:
            match_pattern = cfg.get("match_pattern")
            unified_text = cfg.get("unified_text")
            clear_pattern = cfg.get("clear_pattern")
            
            if re.search(match_pattern, norm, re.IGNORECASE):
                p.text = unified_text
                p.alignment = 1  # Centered
                p.paragraph_format.keep_with_next = True
                for run in p.runs:
                    run.bold = True
                    run.font.name = "Mangal"
                    
            elif clear_pattern and re.search(clear_pattern, norm, re.IGNORECASE):
                p.text = ""
                
        i += 1
