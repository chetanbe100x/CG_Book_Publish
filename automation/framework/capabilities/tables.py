from __future__ import annotations

from typing import Any, Sequence

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from ..core.package import NS


def inventory(root: etree._Element) -> dict[str, int]:
    return {
        "tables": len(root.findall(".//w:tbl", NS)),
        "rows": len(root.findall(".//w:tr", NS)),
        "cells": len(root.findall(".//w:tc", NS)),
        "fixed_row_heights": len(root.findall(".//w:trHeight", NS)),
    }


def _dxa_element(parent: Any, tag: str, value: int) -> Any:
    element = parent.find(qn(f"w:{tag}"))
    if element is None:
        element = OxmlElement(f"w:{tag}")
        parent.append(element)
    element.set(qn("w:type"), "dxa")
    element.set(qn("w:w"), str(int(value)))
    return element


def set_row_cant_split(row: Any) -> None:
    properties = row._tr.get_or_add_trPr()
    if properties.find(qn("w:cantSplit")) is None:
        properties.append(OxmlElement("w:cantSplit"))


def set_exact_geometry(
    table: Any,
    column_widths_twips: Sequence[int],
    *,
    indent_twips: int = 0,
    cell_margins_twips: tuple[int, int, int, int] = (0, 0, 0, 0),
    prevent_row_split: bool = True,
) -> None:
    """Set a fixed Word table grid whose tblW, tblGrid and tcW agree."""
    widths = tuple(int(value) for value in column_widths_twips)
    if not widths or any(value <= 0 for value in widths):
        raise ValueError("column_widths_twips must contain positive widths")
    if len(widths) != len(table.columns):
        raise ValueError("column_widths_twips must match the table column count")

    properties = table._tbl.tblPr
    _dxa_element(properties, "tblW", sum(widths))
    _dxa_element(properties, "tblInd", int(indent_twips))
    layout = properties.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        properties.append(layout)
    layout.set(qn("w:type"), "fixed")

    margins = properties.find(qn("w:tblCellMar"))
    if margins is None:
        margins = OxmlElement("w:tblCellMar")
        properties.append(margins)
    for tag, value in zip(
        ("top", "right", "bottom", "left"),
        cell_margins_twips,
        strict=True,
    ):
        _dxa_element(margins, tag, int(value))

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)

    table.autofit = False
    for row in table.rows:
        if prevent_row_split:
            set_row_cant_split(row)
        for column_index, cell in enumerate(row.cells):
            _dxa_element(cell._tc.get_or_add_tcPr(), "tcW", widths[column_index])
