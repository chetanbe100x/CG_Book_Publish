from lxml import etree

from ..core.package import NS


def inventory(root: etree._Element) -> dict[str, int]:
    return {
        "omath": len(root.findall(".//m:oMath", NS)),
        "omath_paragraphs": len(root.findall(".//m:oMathPara", NS)),
    }
