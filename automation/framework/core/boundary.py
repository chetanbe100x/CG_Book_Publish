from __future__ import annotations

from copy import deepcopy

from lxml import etree

from .models import FrameworkError
from .package import NS, W


class BoundaryError(FrameworkError):
    pass


def _prune_after(element: etree._Element, target: etree._Element, stop: etree._Element) -> None:
    current = target
    while current is not stop:
        parent = current.getparent()
        if parent is None:
            raise BoundaryError("Page boundary is detached from the document body")
        index = parent.index(current)
        for sibling in list(parent)[index + 1 :]:
            parent.remove(sibling)
        current = parent


def selected_body(
    source_body: etree._Element,
    source_pages: int | None,
    *,
    strategy: str = "saved_rendered",
) -> etree._Element:
    body = deepcopy(source_body)
    for section in body.findall("w:sectPr", NS):
        body.remove(section)
    if source_pages is None:
        return body
    if strategy == "saved_rendered":
        breaks = body.findall(".//w:lastRenderedPageBreak", NS)
        if len(breaks) < source_pages:
            raise BoundaryError(
                f"Source contains {len(breaks)} saved Word page boundaries; "
                f"cannot select page {source_pages} without a reviewed adapter"
            )
        target = breaks[source_pages - 1]
        _prune_after(body, target, body)
        return body
    if strategy == "explicit":
        breaks = body.findall(".//w:br[@w:type='page']", NS)
        page_count = len(breaks) + 1
        if source_pages > page_count:
            raise BoundaryError(
                f"Source contains {page_count} explicitly delimited pages; "
                f"cannot select page {source_pages}"
            )
        if source_pages == page_count:
            return body
        target = breaks[source_pages - 1]
        _prune_after(body, target, body)
        parent = target.getparent()
        if parent is None:
            raise BoundaryError("Explicit page boundary is detached")
        parent.remove(target)
        return body
    raise BoundaryError(f"Unknown page-boundary strategy: {strategy}")


def selected_explicit_page_numbers(
    source_body: etree._Element,
    page_numbers: tuple[int, ...],
    *,
    bookmark_prefix: str = "SourcePdfPage",
) -> etree._Element:
    """Select explicitly delimited pages by their stable source-page bookmarks."""
    if not page_numbers:
        raise BoundaryError("Explicit page-number selection requires at least one page")
    if len(set(page_numbers)) != len(page_numbers):
        raise BoundaryError("Explicit page-number selection contains duplicates")

    source = deepcopy(source_body)
    sections = source.findall("w:sectPr", NS)
    for section in sections:
        source.remove(section)

    groups: list[list[etree._Element]] = [[]]
    for child in list(source):
        page_breaks = child.findall(".//w:br[@w:type='page']", NS)
        if page_breaks:
            # The reviewed PDF builder emits a dedicated break paragraph between
            # source pages. Reject mixed-content boundary elements so selection
            # cannot silently discard real content.
            text_value = "".join(child.xpath(".//w:t/text()", namespaces=NS)).strip()
            drawings = child.findall(".//w:drawing", NS)
            tables = child.findall(".//w:tbl", NS)
            if text_value or drawings or tables or len(page_breaks) != 1:
                raise BoundaryError(
                    "Explicit page boundary shares an element with source content"
                )
            groups.append([])
            continue
        groups[-1].append(child)

    mapped: dict[int, list[etree._Element]] = {}
    for group in groups:
        names = [
            str(value)
            for value in (
                node.get(W + "name")
                for child in group
                for node in child.findall(".//w:bookmarkStart", NS)
            )
            if value and value.startswith(bookmark_prefix)
        ]
        if len(names) != 1:
            raise BoundaryError(
                "Each normalized PDF page must have exactly one source-page bookmark"
            )
        suffix = names[0][len(bookmark_prefix) :]
        if not suffix.isdigit():
            raise BoundaryError(f"Invalid source-page bookmark: {names[0]}")
        number = int(suffix)
        if number in mapped:
            raise BoundaryError(f"Duplicate source-page bookmark: {names[0]}")
        mapped[number] = group

    missing = [number for number in page_numbers if number not in mapped]
    if missing:
        raise BoundaryError(
            "Normalized source is missing source pages: "
            + ", ".join(str(value) for value in missing)
        )

    selected = deepcopy(source)
    for child in list(selected):
        selected.remove(child)
    for index, number in enumerate(page_numbers):
        for child in mapped[number]:
            selected.append(deepcopy(child))
        if index < len(page_numbers) - 1:
            paragraph = etree.Element(W + "p", nsmap=source_body.nsmap)
            run = etree.SubElement(paragraph, W + "r")
            page_break = etree.SubElement(run, W + "br")
            page_break.set(W + "type", "page")
            selected.append(paragraph)
    return selected


def boundary_inventory(source_body: etree._Element) -> dict[str, int]:
    return {
        "last_rendered_page_breaks": len(source_body.findall(".//w:lastRenderedPageBreak", NS)),
        "explicit_page_breaks": len(source_body.findall(".//w:br[@w:type='page']", NS)),
        "page_break_before": len(source_body.findall(".//w:pageBreakBefore", NS)),
    }
