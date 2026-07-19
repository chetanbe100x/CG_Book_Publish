from __future__ import annotations

import re
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def get_consonant_cluster_len(s: str, start_idx: int) -> int:
    half_consonants = {
        '[', '/', 'X', '?', 'T', 'D', 'P', 'R', 'F', 'U', 
        'I', 'C', 'H', 'E', 'Y', 'O', 'L', "'", '"'
    }
    n = len(s)
    idx = start_idx
    while idx < n and s[idx] in half_consonants:
        if idx + 1 < n and s[idx + 1] == 'k':
            break
        idx += 1
    if idx < n:
        if s[idx] in half_consonants and idx + 1 < n and s[idx + 1] == 'k':
            idx += 2
        else:
            idx += 1
    if idx < n and s[idx] == 'z':
        idx += 1
    return idx - start_idx

def KrutiDev_to_Unicode(krutidev_substring: str) -> str:
    modified_substring = krutidev_substring
    
    array_one = ["ñ","Q+Z","sas","aa",")Z","ZZ","‘","’","“","”",
    "å",  "ƒ",  "„",   "…",   "†",   "‡",   "ˆ",   "‰",   "Š",   "‹", 
    "¶+",   "d+", "[+k","[+", "x+",  "T+",  "t+", "M+", "<+", "Q+", ";+", "j+", "u+",
    "Ùk", "Ù", "Dr", "–", "—","é","™","=kk","f=k",  
    "à",   "á",    "â",   "ã",   "ºz",  "º",   "í", "{k", "{", "=",  "«",   
    "Nî",   "Vî",    "Bî",   "Mî",   "<î", "|", "K", "}",
    "J",   "Vª",   "Mª",  "<ªª",  "Nª",   "Ø",  "Ý", "nzZ",  "æ", "ç", "Á", "xz", "#", ":",
    "v‚","vks",  "vkS",  "vk",    "v",  "b±", "Ã",  "bZ",  "b",  "m",  "Å",  ",s",  ",",   "_",
    "ô",  "d", "Dk", "D", "[k", "[", "x","Xk", "X", "Ä", "?k", "?",   "³", 
    "pkS",  "p", "Pk", "P",  "N",  "t", "Tk", "T",  ">", "÷", "¥",
    "ê",  "ë",   "V",  "B",   "ì",   "ï", "M+", "<+", "M",  "<", ".k", ".",    
    "r",  "Rk", "R",   "Fk", "F",  ")", "n", "/k", "èk",  "/", "Ë", "è", "u", "Uk", "U",   
    "i",  "Ik", "I",   "Q",    "¶",  "c", "Ck",  "C",  "Hk",  "H", "e", "Ek",  "E",
    ";",  "¸",   "j",    "y", "Yk",  "Y",  "G",  "o", "Ok", "O",
    "'k", "'",   "\"k",  "\"",  "l", "Lk",  "L",   "g", 
    "È", "z", 
    "Ì", "Í", "Î",  "Ï",  "Ñ",  "Ò",  "Ó",  "Ô",   "Ö",  "Ø",  "Ù","Ük", "Ü",
    "‚",    "ks",   "kS",   "k",  "h",    "q",   "w",   "`",    "s",    "S",
    "a",    "¡",    "%",     "W",  "•", "·", "∙", "·", "~j",  "~", "\\","+"," ः",
    "^", "*",  "Þ", "ß", "(", "¼", "½", "¿", "À", "¾", "A", "-", "&", "&", "Œ", "]","~ ","@"]
    
    array_two = ["॰","QZ+","sa","a","र्द्ध","Z","\"","\"","'","'",
    "०",  "१",  "२",  "३",     "४",   "५",  "६",   "७",   "८",   "९",   
    "फ़्",  "क़",  "ख़", "ख़्",  "ग़", "ज़्", "ज़",  "ड़",  "ढ़",   "फ़",  "य़",  "ऱ",  "ऩ",    
    "त्त", "त्त्", "क्त",  "दृ",  "कृ","nn","nnd","=k","f=",
    "ह्न",  "ह्य",  "हृ",  "ह्म",  "ह्र",  "ह्",   "द्द",  "क्ष", "क्ष्", "त्र", "त्र्", 
    "छ्य",  "ट्य",  "ठ्य",  "ड्य",  "ढ्य", "द्य", "ज्ञ", "द्व",
    "श्र",  "ट्र",    "ड्र",    "ढ्र",    "छ्र",   "क्र",  "फ्र", "र्द्र",  "द्र",   "प्र", "प्र",  "ग्र", "रु",  "रू",
    "ऑ",   "ओ",  "औ",  "आ",   "अ", "ईं", "ई",  "ई",   "इ",  "उ",   "ऊ",  "ऐ",  "ए", "ऋ",
    "क्क", "क", "क", "क्", "ख", "ख्", "ग", "ग", "ग्", "घ", "घ", "घ्", "ङ",
    "चै",  "च", "च", "च्", "छ", "ज", "ज", "ज्",  "झ",  "झ्", "ञ",
    "ट्ट",   "ट्ठ",   "ट",   "ठ",   "ड्ड",   "ड्ढ",  "ड़", "ढ़", "ड",   "ढ", "ण", "ण्",   
    "त", "त", "त्", "थ", "थ्",  "द्ध",  "द", "ध", "ध", "ध्", "ध्", "ध्", "न", "न", "न्",    
    "प", "प", "प्",  "फ", "फ्",  "ब", "ब", "ब्",  "भ", "भ्",  "म",  "म", "म्",  
    "य", "य्",  "र", "ल", "ल", "ल्",  "ळ",  "व", "व", "व्",   
    "श", "श्",  "ष", "ष्", "स", "स", "स्", "ह", 
    "ीं", "्र",    
    "द्द", "ट्ट","ट्ठ","ड्ड","कृ","भ","्य","ड्ढ","झ्","क्र","त्त्","श","श्",
    "ॉ",  "ो",   "ौ",   "ा",   "ी",   "ु",   "ू",   "ृ",   "े",   "ै",
    "ं",   "ँ",   "ः",   "ॅ",  "ऽ", "ऽ", "ऽ", "ऽ", "्र",  "्", "?", "़",":",
    "‘",   "’",   "“",   "”",  ";",  "(",    ")",   "{",    "}",   "=", "।", ".", "-",  "µ", "॰", ",","् ","/"]
    
    array_one_length = len(array_one)
    
    modified_substring = "  " + modified_substring + "  "
    position_of_f = modified_substring.rfind("f")
    while (position_of_f != -1):    
        cluster_len = get_consonant_cluster_len(modified_substring, position_of_f + 1)
        before = modified_substring[:position_of_f]
        cluster = modified_substring[position_of_f + 1 : position_of_f + 1 + cluster_len]
        after = modified_substring[position_of_f + 1 + cluster_len:]
        modified_substring = before + cluster + "f" + after
        position_of_f = modified_substring.rfind("f", 0, position_of_f - 1)
    modified_substring = modified_substring.replace("f","ि")
    modified_substring = modified_substring.strip()
    
    modified_substring = "  " + modified_substring + "  "
    position_of_r = modified_substring.find("Z")
    set_of_matras =  ["‚",    "ks",   "kS",   "k",     "h",    "q",   "w",   "`",    "s",    "S", "a",    "¡",    "%",     "W",   "·",   "~ ", "~"]
    while (position_of_r != -1):    
        modified_substring = modified_substring.replace("Z","",1)
        if modified_substring[position_of_r - 1] in set_of_matras:
            modified_substring = modified_substring[:position_of_r - 2] + "j~" + modified_substring[position_of_r - 2:]
        else:
            modified_substring = modified_substring[:position_of_r - 1] + "j~" + modified_substring[position_of_r - 1:]
        position_of_r = modified_substring.find("Z")
    modified_substring = modified_substring.strip()
    
    for input_symbol_idx in range(0, array_one_length):
        modified_substring = modified_substring.replace(array_one[input_symbol_idx] , array_two[input_symbol_idx])
        
    modified_substring = modified_substring.replace("nn", "न्न")
    modified_substring = modified_substring.replace("nnd", "न्न्")
    
    return modified_substring

LEGACY_PREFIXES = ("kruti", "devlys", "kundli", "walkman chanakya", "shusha", "ams")

def is_legacy_font(font_name: str | None) -> bool:
    if not font_name:
        return False
    fn = font_name.strip().lower()
    return any(fn.startswith(prefix) for prefix in LEGACY_PREFIXES)

def convert_runs_to_unicode(src_paragraph, dest_paragraph, target_font: str = "Mangal") -> None:
    for run in src_paragraph.runs:
        font_name = run.font.name
        is_legacy = is_legacy_font(font_name)
        run_text = run.text
        if is_legacy and run_text:
            converted = KrutiDev_to_Unicode(run_text)
            new_run = dest_paragraph.add_run(converted)
        else:
            new_run = dest_paragraph.add_run(run_text)
            
        new_run.bold = run.bold
        new_run.italic = run.italic
        if run.font.color and run.font.color.rgb:
            new_run.font.color.rgb = run.font.color.rgb
        if run.font.size:
            new_run.font.size = run.font.size
        new_run.font.name = target_font if is_legacy else run.font.name

def convert_table_runs(table_xml, target_font: str = "Mangal") -> None:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    
    # Normalize all w:rFonts elements (run and paragraph level default formatting)
    for rFonts in table_xml.findall(".//w:rFonts", namespaces=ns):
        rPr = rFonts.getparent()
        if rPr is None:
            continue
        grandparent = rPr.getparent()
        if grandparent is None:
            continue
            
        text_nodes = grandparent.findall(".//w:t", namespaces=ns)
        text_val = "".join([t.text for t in text_nodes if t.text])
        
        font_name = rFonts.get(qn("w:ascii"))
        is_legacy = is_legacy_font(font_name)
        
        if is_legacy:
            for t in text_nodes:
                if t.text:
                    t.text = KrutiDev_to_Unicode(t.text)
                    
        # Map fonts: if legacy or Devanagari characters, map to Mangal; else to Times New Roman
        is_hindi = is_legacy or any(('\u0900' <= char <= '\u097f' or ord(char) > 127) for char in text_val)
        chosen_font = target_font if is_hindi else "Times New Roman"
        
        rFonts.set(qn("w:ascii"), chosen_font)
        rFonts.set(qn("w:hAnsi"), chosen_font)
        rFonts.set(qn("w:cs"), chosen_font)
        rFonts.set(qn("w:hint"), "default")
        
    # Prevent row splitting
    for tr in table_xml.findall(".//w:tr", namespaces=ns):
        trPr = tr.get_or_add_trPr()
        if trPr.find("w:cantSplit", namespaces=ns) is None:
            trPr.append(OxmlElement("w:cantSplit"))
