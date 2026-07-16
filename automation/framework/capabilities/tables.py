from lxml import etree

from ..core.package import NS


def inventory(root: etree._Element) -> dict[str, int]:
    return {
        "tables": len(root.findall(".//w:tbl", NS)),
        "rows": len(root.findall(".//w:tr", NS)),
        "cells": len(root.findall(".//w:tc", NS)),
        "fixed_row_heights": len(root.findall(".//w:trHeight", NS)),
    }
