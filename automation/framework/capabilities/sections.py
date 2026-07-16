from lxml import etree

from ..core.package import NS, W


def inventory(root: etree._Element) -> dict[str, object]:
    sections = root.findall(".//w:sectPr", NS)
    geometry: list[dict[str, str]] = []
    for section in sections:
        page = section.find("w:pgSz", NS)
        margin = section.find("w:pgMar", NS)
        geometry.append(
            {
                "width_twips": page.get(W + "w", "") if page is not None else "",
                "height_twips": page.get(W + "h", "") if page is not None else "",
                "orientation": page.get(W + "orient", "portrait") if page is not None else "",
                "top_twips": margin.get(W + "top", "") if margin is not None else "",
                "right_twips": margin.get(W + "right", "") if margin is not None else "",
                "bottom_twips": margin.get(W + "bottom", "") if margin is not None else "",
                "left_twips": margin.get(W + "left", "") if margin is not None else "",
            }
        )
    return {"section_count": len(sections), "geometry": geometry}
