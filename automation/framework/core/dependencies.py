from __future__ import annotations

import posixpath
import re
from copy import deepcopy
from pathlib import PurePosixPath

from lxml import etree

from .models import FrameworkError, UnsupportedFeatureError
from .package import (
    CT,
    NS,
    PR,
    R,
    W,
    DocxPackage,
    canonical_xml,
    parse_xml,
    relationships_part,
    relative_target,
    resolve_target,
    xml_bytes,
)


def _unique_id(prefix: str, existing: set[str]) -> str:
    index = 1
    while f"{prefix}{index}" in existing:
        index += 1
    value = f"{prefix}{index}"
    existing.add(value)
    return value


def _style_references(root: etree._Element) -> set[str]:
    values: set[str] = set()
    for tag in ("pStyle", "rStyle", "tblStyle"):
        for element in root.findall(f".//w:{tag}", NS):
            value = element.get(W + "val")
            if value:
                values.add(value)
    return values


def merge_styles(
    source: DocxPackage,
    destination_parts: dict[str, bytes],
    selected_body: etree._Element,
) -> tuple[dict[str, str], list[etree._Element]]:
    source_root = source.optional_xml("word/styles.xml")
    destination_data = destination_parts.get("word/styles.xml")
    if source_root is None or destination_data is None:
        if _style_references(selected_body):
            raise UnsupportedFeatureError("Referenced styles cannot be resolved")
        return {}, []
    destination_root = parse_xml(destination_data, "word/styles.xml")
    source_styles = {
        style.get(W + "styleId"): style
        for style in source_root.findall("w:style", NS)
        if style.get(W + "styleId")
    }
    destination_styles = {
        style.get(W + "styleId"): style
        for style in destination_root.findall("w:style", NS)
        if style.get(W + "styleId")
    }
    required = set(_style_references(selected_body))
    queue = list(required)
    while queue:
        style_id = queue.pop()
        style = source_styles.get(style_id)
        if style is None:
            continue
        for tag in ("basedOn", "next", "link"):
            reference = style.find(f"w:{tag}", NS)
            value = reference.get(W + "val") if reference is not None else None
            if value and value not in required:
                required.add(value)
                queue.append(value)

    existing_ids = set(destination_styles)
    mapping: dict[str, str] = {}
    for style_id in sorted(required):
        source_style = source_styles.get(style_id)
        if source_style is None:
            continue
        destination_style = destination_styles.get(style_id)
        if destination_style is None or canonical_xml(destination_style) == canonical_xml(source_style):
            mapping[style_id] = style_id
            existing_ids.add(style_id)
            continue
        safe = re.sub(r"[^A-Za-z0-9_]", "_", style_id) or "Style"
        candidate = f"src_{safe}"
        suffix = 2
        while candidate in existing_ids:
            candidate = f"src_{safe}_{suffix}"
            suffix += 1
        mapping[style_id] = candidate
        existing_ids.add(candidate)

    for tag in ("pStyle", "rStyle", "tblStyle"):
        for element in selected_body.findall(f".//w:{tag}", NS):
            value = element.get(W + "val")
            if value in mapping:
                element.set(W + "val", mapping[value])

    copied: list[etree._Element] = []
    for style_id in sorted(required):
        source_style = source_styles.get(style_id)
        if source_style is None:
            continue
        mapped_id = mapping[style_id]
        existing = destination_styles.get(mapped_id)
        if existing is not None and canonical_xml(existing) == canonical_xml(source_style):
            continue
        clone = deepcopy(source_style)
        clone.set(W + "styleId", mapped_id)
        for tag in ("basedOn", "next", "link"):
            reference = clone.find(f"w:{tag}", NS)
            if reference is not None:
                value = reference.get(W + "val")
                if value in mapping:
                    reference.set(W + "val", mapping[value])
        destination_root.append(clone)
        copied.append(clone)
    destination_parts["word/styles.xml"] = xml_bytes(destination_root)
    return mapping, copied


def merge_numbering(
    source: DocxPackage,
    destination_parts: dict[str, bytes],
    selected_body: etree._Element,
    copied_styles: list[etree._Element],
) -> dict[int, int]:
    source_root = source.optional_xml("word/numbering.xml")
    if source_root is None:
        return {}
    destination_root = (
        parse_xml(destination_parts["word/numbering.xml"], "word/numbering.xml")
        if "word/numbering.xml" in destination_parts
        else etree.Element(W + "numbering", nsmap={"w": NS["w"]})
    )
    roots = [selected_body, *copied_styles]
    required: set[int] = set()
    for root in roots:
        for element in root.findall(".//w:numId", NS):
            value = element.get(W + "val")
            if value and value.lstrip("-").isdigit() and int(value) > 0:
                required.add(int(value))
    source_nums = {
        int(element.get(W + "numId")): element
        for element in source_root.findall("w:num", NS)
        if element.get(W + "numId", "").isdigit()
    }
    source_abstract = {
        int(element.get(W + "abstractNumId")): element
        for element in source_root.findall("w:abstractNum", NS)
        if element.get(W + "abstractNumId", "").isdigit()
    }
    used_num = {
        int(element.get(W + "numId"))
        for element in destination_root.findall("w:num", NS)
        if element.get(W + "numId", "").isdigit()
    }
    used_abstract = {
        int(element.get(W + "abstractNumId"))
        for element in destination_root.findall("w:abstractNum", NS)
        if element.get(W + "abstractNumId", "").isdigit()
    }
    num_mapping: dict[int, int] = {}
    abstract_mapping: dict[int, int] = {}
    for old_num in sorted(required):
        num = source_nums.get(old_num)
        if num is None:
            raise UnsupportedFeatureError(f"Numbering definition {old_num} is missing")
        abstract_ref = num.find("w:abstractNumId", NS)
        old_abstract = int(abstract_ref.get(W + "val")) if abstract_ref is not None else 0
        if old_abstract not in abstract_mapping:
            new_abstract = old_abstract
            if new_abstract in used_abstract:
                new_abstract = max(used_abstract | {0}) + 1
            used_abstract.add(new_abstract)
            abstract_mapping[old_abstract] = new_abstract
            abstract = source_abstract.get(old_abstract)
            if abstract is None:
                raise UnsupportedFeatureError(f"Abstract numbering {old_abstract} is missing")
            if abstract.find(".//w:lvlPicBulletId", NS) is not None:
                raise UnsupportedFeatureError("Picture bullets require a reviewed numbering adapter")
            abstract_clone = deepcopy(abstract)
            abstract_clone.set(W + "abstractNumId", str(new_abstract))
            first_num = destination_root.find("w:num", NS)
            if first_num is None:
                destination_root.append(abstract_clone)
            else:
                destination_root.insert(destination_root.index(first_num), abstract_clone)
        new_num = old_num
        if new_num in used_num:
            new_num = max(used_num | {0}) + 1
        used_num.add(new_num)
        num_mapping[old_num] = new_num
        clone = deepcopy(num)
        clone.set(W + "numId", str(new_num))
        reference = clone.find("w:abstractNumId", NS)
        if reference is not None:
            reference.set(W + "val", str(abstract_mapping[old_abstract]))
        destination_root.append(clone)

    for root in roots:
        for element in root.findall(".//w:numId", NS):
            value = element.get(W + "val")
            if value and value.lstrip("-").isdigit() and int(value) in num_mapping:
                element.set(W + "val", str(num_mapping[int(value)]))
    if copied_styles:
        destination_parts["word/styles.xml"] = xml_bytes(
            copied_styles[0].getroottree().getroot()
        )
    destination_parts["word/numbering.xml"] = xml_bytes(destination_root)
    return num_mapping


def merge_fonts(
    source: DocxPackage,
    destination_parts: dict[str, bytes],
    selected_body: etree._Element,
    copied_styles: list[etree._Element],
) -> list[str]:
    source_root = source.optional_xml("word/fontTable.xml")
    destination_data = destination_parts.get("word/fontTable.xml")
    if source_root is None or destination_data is None:
        return []
    destination_root = parse_xml(destination_data, "word/fontTable.xml")
    required: set[str] = set()
    for root in [selected_body, *copied_styles]:
        for element in root.findall(".//w:rFonts", NS):
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                value = element.get(W + attribute)
                if value and not value.startswith("+"):
                    required.add(value)
    source_fonts = {
        element.get(W + "name"): element
        for element in source_root.findall("w:font", NS)
        if element.get(W + "name")
    }
    destination_fonts = {
        element.get(W + "name"): element
        for element in destination_root.findall("w:font", NS)
        if element.get(W + "name")
    }
    merged: list[str] = []
    for name in sorted(required, key=str.casefold):
        source_font = source_fonts.get(name)
        if source_font is None:
            continue
        if any(attribute.startswith(R) for node in source_font.iter() for attribute in node.attrib):
            raise UnsupportedFeatureError(f"Embedded font relationship for {name} requires review")
        clone = deepcopy(source_font)
        existing = destination_fonts.get(name)
        if existing is not None:
            destination_root.replace(existing, clone)
        else:
            destination_root.append(clone)
        merged.append(name)
    destination_parts["word/fontTable.xml"] = xml_bytes(destination_root)
    return merged


class RelationshipCopier:
    def __init__(self, source: DocxPackage, destination_parts: dict[str, bytes]):
        self.source = source
        self.destination_parts = destination_parts
        self.content_types = parse_xml(destination_parts["[Content_Types].xml"], "[Content_Types].xml")
        self.source_content_types = source.xml("[Content_Types].xml")
        self.part_mapping: dict[str, str] = {}

    def _copy_content_type(self, source_part: str, destination_part: str) -> None:
        source_name = "/" + source_part
        destination_name = "/" + destination_part
        source_override = next(
            (node for node in self.source_content_types.findall("ct:Override", NS) if node.get("PartName") == source_name),
            None,
        )
        if source_override is not None:
            existing = next(
                (node for node in self.content_types.findall("ct:Override", NS) if node.get("PartName") == destination_name),
                None,
            )
            if existing is None:
                clone = deepcopy(source_override)
                clone.set("PartName", destination_name)
                self.content_types.append(clone)
        extension = PurePosixPath(destination_part).suffix.lstrip(".").lower()
        if extension:
            source_default = next(
                (node for node in self.source_content_types.findall("ct:Default", NS) if node.get("Extension", "").lower() == extension),
                None,
            )
            destination_default = next(
                (node for node in self.content_types.findall("ct:Default", NS) if node.get("Extension", "").lower() == extension),
                None,
            )
            if source_default is not None and destination_default is None:
                self.content_types.append(deepcopy(source_default))

    def _unique_part_name(self, source_part: str) -> str:
        if source_part not in self.destination_parts:
            return source_part
        if self.destination_parts[source_part] == self.source.parts[source_part]:
            return source_part
        path = PurePosixPath(source_part)
        index = 1
        while True:
            candidate = str(path.with_name(f"{path.stem}_src{index}{path.suffix}"))
            if candidate not in self.destination_parts:
                return candidate
            index += 1

    def copy_part(self, source_part: str) -> str:
        if source_part in self.part_mapping:
            return self.part_mapping[source_part]
        if source_part not in self.source.parts:
            raise UnsupportedFeatureError(f"Relationship target is missing: {source_part}")
        destination_part = self._unique_part_name(source_part)
        self.part_mapping[source_part] = destination_part
        self.destination_parts[destination_part] = self.source.parts[source_part]
        self._copy_content_type(source_part, destination_part)

        source_rels_name = relationships_part(source_part)
        if source_rels_name in self.source.parts:
            rels_root = parse_xml(self.source.parts[source_rels_name], source_rels_name)
            for rel in rels_root.findall("pr:Relationship", NS):
                if rel.get("TargetMode") == "External":
                    continue
                child_source = resolve_target(source_part, rel.get("Target", ""))
                child_destination = self.copy_part(child_source)
                rel.set("Target", relative_target(destination_part, child_destination))
            destination_rels_name = relationships_part(destination_part)
            self.destination_parts[destination_rels_name] = etree.tostring(
                rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        return destination_part

    def copy_document_relationships(self, selected_body: etree._Element) -> dict[str, str]:
        source_rels = self.source.optional_xml("word/_rels/document.xml.rels")
        if source_rels is None:
            return {}
        destination_rels = (
            parse_xml(self.destination_parts["word/_rels/document.xml.rels"], "word/_rels/document.xml.rels")
            if "word/_rels/document.xml.rels" in self.destination_parts
            else etree.Element(PR + "Relationships", nsmap={None: NS["pr"]})
        )
        source_map = {rel.get("Id"): rel for rel in source_rels.findall("pr:Relationship", NS)}
        existing_ids = {rel.get("Id", "") for rel in destination_rels.findall("pr:Relationship", NS)}
        referenced: set[str] = set()
        for element in selected_body.iter():
            for attribute, value in element.attrib.items():
                if attribute in (R + "id", R + "embed", R + "link"):
                    referenced.add(value)
        mapping: dict[str, str] = {}
        for source_id in sorted(referenced):
            source_rel = source_map.get(source_id)
            if source_rel is None:
                raise UnsupportedFeatureError(f"Body relationship {source_id} is missing")
            new_id = _unique_id("rIdSrc", existing_ids)
            clone = deepcopy(source_rel)
            clone.set("Id", new_id)
            if source_rel.get("TargetMode") != "External":
                source_part = resolve_target("word/document.xml", source_rel.get("Target", ""))
                destination_part = self.copy_part(source_part)
                clone.set("Target", relative_target("word/document.xml", destination_part))
            destination_rels.append(clone)
            mapping[source_id] = new_id
        for element in selected_body.iter():
            for attribute, value in list(element.attrib.items()):
                if attribute in (R + "id", R + "embed", R + "link") and value in mapping:
                    element.set(attribute, mapping[value])
        self.destination_parts["word/_rels/document.xml.rels"] = etree.tostring(
            destination_rels, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        self.destination_parts["[Content_Types].xml"] = etree.tostring(
            self.content_types, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        return mapping


def disable_automatic_field_updates(destination_parts: dict[str, bytes]) -> None:
    data = destination_parts.get("word/settings.xml")
    if data is None:
        return
    root = parse_xml(data, "word/settings.xml")
    for element in root.findall(".//w:updateFields", NS):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    destination_parts["word/settings.xml"] = xml_bytes(root)


def disable_automatic_image_compression(
    destination_parts: dict[str, bytes],
) -> None:
    data = destination_parts.get("word/settings.xml")
    if data is None:
        return
    root = parse_xml(data, "word/settings.xml")
    element = root.find(".//w:doNotAutoCompressPictures", NS)
    if element is None:
        element = etree.SubElement(root, W + "doNotAutoCompressPictures")
        successor = next(
            (
                root.find(f"w:{name}", NS)
                for name in ("shapeDefaults", "decimalSymbol", "listSeparator")
                if root.find(f"w:{name}", NS) is not None
            ),
            None,
        )
        if successor is not None:
            successor.addprevious(element)
    element.set(W + "val", "true")
    destination_parts["word/settings.xml"] = xml_bytes(root)
