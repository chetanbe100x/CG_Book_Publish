from lxml import etree

from ..core.package import NS


def inventory(root: etree._Element) -> dict[str, object]:
    instructions = [
        "".join(element.itertext()).strip()
        for element in root.findall(".//w:instrText", NS)
    ]
    return {
        "field_chars": len(root.findall(".//w:fldChar", NS)),
        "simple_fields": len(root.findall(".//w:fldSimple", NS)),
        "field_instructions": instructions,
        "hyperlinks": len(root.findall(".//w:hyperlink", NS)),
        "bookmarks": len(root.findall(".//w:bookmarkStart", NS)),
    }
