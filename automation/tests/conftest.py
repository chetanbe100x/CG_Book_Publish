from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOKS_DIR = PROJECT_ROOT / "Books"
PROFILES_DIR = PROJECT_ROOT / "automation" / "framework" / "profiles"

DISCOVERY_ERRORS: list[str] = []

def discover_jobs() -> list[tuple[str, dict, Path]]:
    """Scan Books/ tree, yield (job_id, raw_json, job_json_path) for each registered book."""
    jobs = []
    if BOOKS_DIR.is_dir():
        for p in BOOKS_DIR.rglob("job.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                job_id = data.get("job_id")
                if job_id:
                    jobs.append((str(job_id), data, p))
                else:
                    DISCOVERY_ERRORS.append(f"Job file {p} is missing 'job_id'")
            except Exception as exc:
                DISCOVERY_ERRORS.append(f"Job file {p} failed to load: {exc}")
    return jobs

def discover_profiles() -> list[tuple[str, dict]]:
    """Scan profiles/ dir, yield (profile_name, profile_data) for each profile."""
    profiles = []
    if PROFILES_DIR.is_dir():
        for p in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                profiles.append((p.name[:-5], data))
            except Exception as exc:
                DISCOVERY_ERRORS.append(f"Profile {p} failed to load: {exc}")
    return profiles

def all_required_fonts() -> set[str]:
    """Collect every font declared in required_fonts across all jobs."""
    fonts = set()
    for _, job_data, _ in discover_jobs():
        for font in job_data.get("required_fonts", []):
            fonts.add(str(font))
    return fonts

def all_font_maps() -> list[tuple[str, dict]]:
    """Collect every pdf_font_map across all jobs."""
    maps = []
    for job_id, job_data, _ in discover_jobs():
        font_map = job_data.get("pdf_font_map")
        if font_map:
            maps.append((job_id, font_map))
    return maps

def all_chapter_patterns() -> list[tuple[str, str]]:
    """Collect every regex pattern from chapter_structure + chapter_integration across all jobs."""
    patterns = []
    for job_id, job_data, _ in discover_jobs():
        # chapter_structure logical_order and heading_unification
        struct = job_data.get("chapter_structure", {})
        for lo in struct.get("logical_order", []):
            for key in ("match", "insert_before_pattern"):
                if lo.get(key):
                    patterns.append((job_id, lo[key]))
        for hu in struct.get("heading_unification", []):
            for key in ("match_pattern", "clear_pattern"):
                if hu.get(key):
                    patterns.append((job_id, hu[key]))
        
        # chapter_integration chapters
        integration = job_data.get("chapter_integration", {})
        for ch in integration.get("chapters", []):
            for key in ("ref_start_pattern", "ref_end_pattern", "insert_before_pattern"):
                if ch.get(key):
                    patterns.append((job_id, ch[key]))
            for pair in ch.get("bilingual_pairing", []):
                for key in ("hindi_start_pattern", "english_start_pattern"):
                    if pair.get(key):
                        patterns.append((job_id, pair[key]))
    return patterns
