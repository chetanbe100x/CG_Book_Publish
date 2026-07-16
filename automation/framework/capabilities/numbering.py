from lxml import etree

from ..core.package import NS, W


def used_num_ids(root: etree._Element) -> list[int]:
    values: set[int] = set()
    for element in root.findall(".//w:numId", NS):
        value = element.get(W + "val")
        if value and value.lstrip("-").isdigit():
            values.add(int(value))
    return sorted(values)


def inventory(root: etree._Element) -> dict[str, object]:
    return {
        "num_properties": len(root.findall(".//w:numPr", NS)),
        "used_num_ids": used_num_ids(root),
    }
