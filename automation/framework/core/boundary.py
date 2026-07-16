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


def selected_body(source_body: etree._Element, source_pages: int | None) -> etree._Element:
    body = deepcopy(source_body)
    for section in body.findall("w:sectPr", NS):
        body.remove(section)
    if source_pages is None:
        return body
    breaks = body.findall(".//w:lastRenderedPageBreak", NS)
    if len(breaks) < source_pages:
        raise BoundaryError(
            f"Source contains {len(breaks)} saved Word page boundaries; "
            f"cannot select page {source_pages} without a reviewed adapter"
        )
    target = breaks[source_pages - 1]
    _prune_after(body, target, body)
    return body


def boundary_inventory(source_body: etree._Element) -> dict[str, int]:
    return {
        "last_rendered_page_breaks": len(source_body.findall(".//w:lastRenderedPageBreak", NS)),
        "explicit_page_breaks": len(source_body.findall(".//w:br[@w:type='page']", NS)),
        "page_break_before": len(source_body.findall(".//w:pageBreakBefore", NS)),
    }
