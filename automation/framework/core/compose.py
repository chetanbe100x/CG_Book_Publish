from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..capabilities.typography import missing_fonts, referenced_fonts
from .boundary import selected_body, selected_explicit_page_numbers
from .dependencies import (
    RelationshipCopier,
    disable_automatic_field_updates,
    disable_automatic_image_compression,
    merge_fonts,
    merge_numbering,
    merge_styles,
)
from .models import JobConfig, StatusStore, UnsupportedFeatureError, sha256_file
from .package import DocxPackage, NS, W, write_new_docx, xml_bytes, parse_xml


BLOCKED_XPATHS = {
    "altChunk": ".//w:altChunk",
    "footnoteReference": ".//w:footnoteReference",
    "endnoteReference": ".//w:endnoteReference",
    "commentReference": ".//w:commentReference",
    "dataBinding": ".//w:dataBinding",
}


def _fidelity_gate(body: etree._Element) -> None:
    blocked = [name for name, xpath in BLOCKED_XPATHS.items() if body.find(xpath, NS) is not None]
    if blocked:
        raise UnsupportedFeatureError(
            "A reviewed adapter is required for: " + ", ".join(sorted(blocked))
        )


def _template_section(body: etree._Element) -> etree._Element:
    sections = body.findall("w:sectPr", NS)
    if not sections:
        raise UnsupportedFeatureError("Template body has no final section properties")
    return deepcopy(sections[-1])


def _replace_template_body(
    template_document: etree._Element,
    selected: etree._Element,
    job: JobConfig,
    source: DocxPackage,
) -> None:
    template_body = template_document.find("w:body", NS)
    if template_body is None:
        raise UnsupportedFeatureError("Template has no document body")
    final_section = _template_section(template_body)
    
    if job.source_style_policy == "content_only":
        source_sect = source.body().find("w:sectPr", NS)
        if source_sect is not None:
            source_pg_mar = source_sect.find("w:pgMar", NS)
            if source_pg_mar is not None:
                final_pg_mar = final_section.find("w:pgMar", NS)
                if final_pg_mar is not None:
                    final_section.replace(final_pg_mar, deepcopy(source_pg_mar))

    for child in list(template_body):
        template_body.remove(child)
    for child in list(selected):
        if child.tag != W + "sectPr":
            template_body.append(deepcopy(child))
    template_body.append(final_section)


def selected_composition_body(
    job: JobConfig,
    source_body: etree._Element,
    source_pages: int | None,
) -> etree._Element:
    if (
        source_pages is not None
        and job.source_type == "pdf"
        and job.preview_source_page_numbers
    ):
        return selected_explicit_page_numbers(
            source_body, job.preview_source_page_numbers
        )
    return selected_body(source_body, source_pages, strategy=job.boundary_strategy)


def compose(job: JobConfig, output: Path, source_pages: int | None) -> dict[str, Any]:
    source = DocxPackage(job.composition_source)
    template = DocxPackage(job.template)
    selected = selected_composition_body(job, source.body(), source_pages)
    _fidelity_gate(selected)
    destination_parts = template.clone_parts()
    
    if job.source_style_policy == "content_only":
        settings_xml = parse_xml(destination_parts["word/settings.xml"], "word/settings.xml")
        mirror = settings_xml.find("w:mirrorMargins", NS)
        if mirror is None:
            mirror = OxmlElement("w:mirrorMargins")
            mirror.set(qn("w:val"), "true")
            settings_xml.append(mirror)
            destination_parts["word/settings.xml"] = xml_bytes(settings_xml)

    style_mapping, copied_styles = merge_styles(source, destination_parts, selected)
    font_roots = [selected, *copied_styles]
    fonts = sorted({font for root in font_roots for font in referenced_fonts(root)}, key=str.casefold)
    absent = missing_fonts(fonts, job.required_fonts)
    if absent:
        raise UnsupportedFeatureError("Required fonts are not installed: " + ", ".join(absent))
    numbering_mapping = merge_numbering(source, destination_parts, selected, copied_styles)
    merged_fonts = merge_fonts(source, destination_parts, selected, copied_styles)
    relationship_mapping = RelationshipCopier(source, destination_parts).copy_document_relationships(selected)

    template_document = template.document()
    _replace_template_body(template_document, selected, job, source)
    destination_parts["word/document.xml"] = xml_bytes(template_document)
    disable_automatic_field_updates(destination_parts)
    disable_automatic_image_compression(destination_parts)
    write_new_docx(output, destination_parts)
    return {
        "output": str(output),
        "sha256": sha256_file(output),
        "source_pages": source_pages,
        "source_page_numbers": (
            list(job.preview_source_page_numbers)
            if source_pages is not None
            else list(job.content_page_numbers)
        ),
        "style_mapping": style_mapping,
        "numbering_mapping": numbering_mapping,
        "merged_fonts": merged_fonts,
        "relationship_mapping": relationship_mapping,
    }


def create_preview(job: JobConfig) -> dict[str, Any]:
    result = compose(job, job.preview_output, job.preview_page_count)
    StatusStore(job).transition(
        "preview_generated",
        preview_sha256=result["sha256"],
        source_sha256=sha256_file(job.source),
        template_sha256=sha256_file(job.template),
        prepared_source_sha256=(
            sha256_file(job.prepared_source)
            if job.prepared_source is not None
            else None
        ),
        approved_reference_sha256=(
            sha256_file(job.approved_reference)
            if job.approved_reference is not None
            else None
        ),
        normalized_source_sha256=(
            sha256_file(job.normalized_source)
            if job.normalized_source is not None
            else None
        ),
        content_manifest_sha256=(
            sha256_file(job.content_manifest)
            if job.content_manifest is not None
            else None
        ),
        layout_reference_sha256=(
            sha256_file(job.layout_reference)
            if job.layout_reference is not None
            else None
        ),
    )
    return result


def create_full(job: JobConfig) -> dict[str, Any]:
    StatusStore(job).require_approved_preview()
    if job.source_type == "pdf":
        from ..ingest.ir import manifest_scope

        assert job.content_manifest is not None
        if manifest_scope(job.content_manifest) != "full":
            raise UnsupportedFeatureError(
                "Full conversion is blocked because the reviewed PDF manifest "
                "contains only the representative preview pages"
            )
    result = compose(job, job.final_output, None)
    StatusStore(job).transition("full_generated", final_sha256=result["sha256"])
    return result
