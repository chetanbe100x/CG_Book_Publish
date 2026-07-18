from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree

from ..capabilities import equations, images_vml
from ..core.audit import body_tokens
from ..core.boundary import selected_body
from ..core.models import JobConfig, sha256_file
from ..core.package import DocxPackage, NS, W, canonical_xml


def _tokens_from_root(root: etree._Element) -> list[str]:
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


def _counts(root: etree._Element) -> dict[str, int]:
    values = {
        "paragraphs": len(root.findall(".//w:p", NS)),
        "runs": len(root.findall(".//w:r", NS)),
        "tables": len(root.findall(".//w:tbl", NS)),
        "num_properties": len(root.findall(".//w:numPr", NS)),
    }
    values.update({key: int(value) for key, value in equations.inventory(root).items()})
    values.update(
        {
            key: int(value)
            for key, value in images_vml.inventory(root).items()
            if key != "media_parts"
        }
    )
    return values


def _final_section(package: DocxPackage) -> etree._Element | None:
    sections = package.body().findall("w:sectPr", NS)
    return sections[-1] if sections else None


def validate_output(job: JobConfig, output: Path, source_pages: int | None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not output.is_file():
        return {"passed": False, "errors": [f"Output is missing: {output}"], "warnings": []}
    source = DocxPackage(job.composition_source)
    template = DocxPackage(job.template)
    result = DocxPackage(output)
    selected = selected_body(
        source.body(),
        source_pages,
        strategy=job.boundary_strategy,
    )

    expected_tokens = _tokens_from_root(selected)
    actual_tokens = body_tokens(output)
    if expected_tokens != actual_tokens:
        errors.append(
            f"Body token mismatch: expected {len(expected_tokens)}, got {len(actual_tokens)}"
        )

    expected_counts = _counts(selected)
    actual_counts = _counts(result.body())
    for key, expected in expected_counts.items():
        actual = actual_counts.get(key)
        if actual != expected:
            errors.append(f"{key} mismatch: expected {expected}, got {actual}")

    invalid_xml = result.invalid_xml_parts()
    if invalid_xml:
        errors.append("Malformed XML parts: " + ", ".join(invalid_xml))
    broken = result.broken_relationships()
    if broken:
        errors.append(f"Broken package relationships: {len(broken)}")

    template_section = _final_section(template)
    result_section = _final_section(result)
    if template_section is None or result_section is None:
        errors.append("Template or output final section properties are missing")
    elif canonical_xml(template_section) != canonical_xml(result_section):
        errors.append("Output page geometry/section properties differ from the template")

    for name, data in template.parts.items():
        if name.startswith(("word/header", "word/footer")) and result.parts.get(name) != data:
            errors.append(f"Template recurring part changed: {name}")

    settings = result.optional_xml("word/settings.xml")
    if settings is not None and settings.find(".//w:updateFields", NS) is not None:
        errors.append("Automatic field updating is enabled")

    return {
        "passed": not errors,
        "output": str(output),
        "sha256": sha256_file(output),
        "source_pages": source_pages,
        "expected_counts": expected_counts,
        "actual_counts": actual_counts,
        "errors": errors,
        "warnings": warnings,
    }


def compare_with_approved(job: JobConfig, candidate: Path) -> dict[str, Any]:
    if job.approved_reference is None:
        return {"passed": True, "errors": [], "warnings": ["No approved reference configured"]}
    approved = DocxPackage(job.approved_reference)
    result = DocxPackage(candidate)
    errors: list[str] = []
    if body_tokens(job.approved_reference) != body_tokens(candidate):
        errors.append("Candidate body tokens differ from approved output")
    approved_counts = _counts(approved.body())
    candidate_counts = _counts(result.body())
    if approved_counts != candidate_counts:
        errors.append("Candidate structural counts differ from approved output")
    for name, data in approved.parts.items():
        if name.startswith(("word/header", "word/footer")) and result.parts.get(name) != data:
            errors.append(f"Candidate differs in approved recurring part: {name}")
    return {
        "passed": not errors,
        "approved_sha256": sha256_file(job.approved_reference),
        "candidate_sha256": sha256_file(candidate),
        "approved_counts": approved_counts,
        "candidate_counts": candidate_counts,
        "errors": errors,
        "warnings": [],
    }
