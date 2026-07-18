from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ..capabilities import equations, fields_links, images_vml, numbering, sections, tables, typography
from ..ingest.pdf import pdf_inventory
from .models import JobConfig, StatusStore, atomic_json_write, sha256_file, utc_now
from .package import DocxPackage, NS, R, W, part_hash


def _visible_tokens(root: etree._Element) -> list[str]:
    tokens: list[str] = []
    for element in root.iter():
        if element.tag == W + "t":
            tokens.append("T:" + (element.text or ""))
        elif element.tag == W + "tab":
            tokens.append("TAB")
        elif element.tag == W + "br":
            tokens.append("BR:" + element.get(W + "type", "textWrapping"))
        elif element.tag == W + "cr":
            tokens.append("CR")
    return tokens


def _digest_json(value: Any) -> str:
    import hashlib

    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _used_style_ids(root: etree._Element) -> list[str]:
    values: set[str] = set()
    for tag in ("pStyle", "rStyle", "tblStyle"):
        for element in root.findall(f".//w:{tag}", NS):
            value = element.get(W + "val")
            if value:
                values.add(value)
    return sorted(values)


def _external_relationships(package: DocxPackage) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for name, data in package.parts.items():
        if not name.endswith(".rels"):
            continue
        root = etree.fromstring(data)
        for rel in root:
            if rel.get("TargetMode") == "External":
                values.append(
                    {
                        "relationships_part": name,
                        "id": rel.get("Id", ""),
                        "type": rel.get("Type", ""),
                        "target": rel.get("Target", ""),
                    }
                )
    return values


def _settings_inventory(package: DocxPackage) -> dict[str, object]:
    settings = package.optional_xml("word/settings.xml")
    if settings is None:
        return {"update_fields": False, "update_fields_values": []}
    fields = settings.findall(".//w:updateFields", NS)
    return {
        "update_fields": bool(fields),
        "update_fields_values": [field.get(W + "val", "true") for field in fields],
    }


def _unsupported_features(body: etree._Element) -> list[str]:
    tests = {
        "altChunk": ".//w:altChunk",
        "embedded_object": ".//w:object",
        "footnotes": ".//w:footnoteReference",
        "endnotes": ".//w:endnoteReference",
        "comments": ".//w:commentReference",
        "data_bound_content_control": ".//w:dataBinding",
        "tracked_insertions": ".//w:ins",
        "tracked_deletions": ".//w:del",
    }
    return sorted(name for name, xpath in tests.items() if body.find(xpath, NS) is not None)


def document_inventory(path: str | Path, include_parts: bool = True) -> dict[str, Any]:
    package = DocxPackage(path)
    body = package.body()
    tokens = _visible_tokens(body)
    styles = package.optional_xml("word/styles.xml")
    font_roots = [body]
    if styles is not None:
        font_roots.append(styles)
    fonts = sorted(
        {font for root in font_roots for font in typography.referenced_fonts(root)},
        key=str.casefold,
    )
    media_count = sum(1 for name in package.parts if name.startswith("word/media/"))
    features: dict[str, Any] = {
        "paragraphs": len(body.findall(".//w:p", NS)),
        "runs": len(body.findall(".//w:r", NS)),
        "text_nodes": len(body.findall(".//w:t", NS)),
        "visible_token_count": len(tokens),
        "visible_tokens_sha256": _digest_json(tokens),
        "visible_text_characters": sum(len(token[2:]) for token in tokens if token.startswith("T:")),
        "last_rendered_page_breaks": len(body.findall(".//w:lastRenderedPageBreak", NS)),
        "explicit_page_breaks": len(body.findall(".//w:br[@w:type='page']", NS)),
        "used_style_ids": _used_style_ids(body),
        "fonts": fonts,
        "font_sizes_points": typography.referenced_sizes(body),
        "unsupported_or_review_features": _unsupported_features(body),
    }
    features.update(equations.inventory(body))
    features.update(numbering.inventory(body))
    features.update(tables.inventory(body))
    features.update(images_vml.inventory(body, media_count))
    features.update(sections.inventory(body))
    features.update(fields_links.inventory(body))

    relationships = sum(1 for name in package.parts if name.endswith(".rels"))
    result: dict[str, Any] = {
        "path": str(package.path),
        "sha256": sha256_file(package.path),
        "size": package.path.stat().st_size,
        "package_part_count": len(package.parts),
        "relationships_part_count": relationships,
        "features": features,
        "settings": _settings_inventory(package),
        "external_relationships": _external_relationships(package),
        "invalid_xml_parts": package.invalid_xml_parts(),
        "broken_relationships": package.broken_relationships(),
    }
    if include_parts:
        result["parts"] = package.part_inventory()
    return result


def audit_job(job: JobConfig) -> dict[str, Any]:
    source_inventory = (
        pdf_inventory(job.source)
        if job.source_type == "pdf"
        else document_inventory(job.source)
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "job": {
            "job_id": job.job_id,
            "class": job.school_class,
            "subject": job.subject,
            "source_type": job.source_type,
            "subject_profile": job.subject_profile,
            "preview_source_pages": job.preview_source_pages,
            "preview_source_page_numbers": list(job.preview_source_page_numbers),
            "content_page_ranges": [list(value) for value in job.content_page_ranges],
            "first_content_side": job.first_content_side,
            "expected_page_count": job.expected_page_count,
            "render_authority": job.render_authority,
            "layout_reference": str(job.layout_reference) if job.layout_reference else None,
            "content_policy": job.content_policy,
            "typography_policy": job.typography_policy,
            "boundary_strategy": job.boundary_strategy,
        },
        "source": source_inventory,
        "template": document_inventory(job.template),
    }
    if job.normalized_source is not None and job.normalized_source.is_file():
        result["normalized_source"] = document_inventory(job.normalized_source)
    if job.approved_reference is not None:
        result["approved_reference"] = document_inventory(job.approved_reference)
    if job.layout_reference is not None:
        result["layout_reference"] = document_inventory(job.layout_reference)
    atomic_json_write(job.audit_path, result)
    StatusStore(job).transition(
        "audited",
        source_sha256=result["source"]["sha256"],
        template_sha256=result["template"]["sha256"],
        approved_reference_sha256=(
            result.get("approved_reference", {}).get("sha256")
            if isinstance(result.get("approved_reference"), dict)
            else None
        ),
        layout_reference_sha256=(
            result.get("layout_reference", {}).get("sha256")
            if isinstance(result.get("layout_reference"), dict)
            else None
        ),
        normalized_source_sha256=(
            sha256_file(job.normalized_source)
            if job.normalized_source is not None and job.normalized_source.is_file()
            else None
        ),
        content_manifest_sha256=(
            sha256_file(job.content_manifest)
            if job.content_manifest is not None and job.content_manifest.is_file()
            else None
        ),
    )
    return result


def body_tokens(path: str | Path) -> list[str]:
    return _visible_tokens(DocxPackage(path).body())


def body_feature_counts(path: str | Path) -> dict[str, int]:
    package = DocxPackage(path)
    body = package.body()
    media_count = sum(1 for name in package.parts if name.startswith("word/media/"))
    counts: dict[str, int] = {
        "paragraphs": len(body.findall(".//w:p", NS)),
        "tables": len(body.findall(".//w:tbl", NS)),
        "runs": len(body.findall(".//w:r", NS)),
        "num_properties": len(body.findall(".//w:numPr", NS)),
    }
    counts.update({k: int(v) for k, v in equations.inventory(body).items()})
    counts.update(
        {
            k: int(v)
            for k, v in images_vml.inventory(body, media_count).items()
            if isinstance(v, int)
        }
    )
    return counts
