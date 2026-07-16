from lxml import etree

from ..core.package import NS


def inventory(root: etree._Element, media_parts: int = 0) -> dict[str, int]:
    return {
        "drawings": len(root.findall(".//w:drawing", NS)),
        "pictures": len(root.findall(".//pic:pic", NS)),
        "vml_elements": len(root.findall(".//v:*", NS)),
        "vml_shapes": len(root.findall(".//v:shape", NS)),
        "media_parts": media_parts,
    }
