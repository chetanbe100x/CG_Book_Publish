from __future__ import annotations

import hashlib
import os
import posixpath
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from lxml import etree

from .models import FrameworkError, IntegrityError

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

W = f"{{{NS['w']}}}"
R = f"{{{NS['r']}}}"
PR = f"{{{NS['pr']}}}"
CT = f"{{{NS['ct']}}}"


def parse_xml(data: bytes, part_name: str = "") -> etree._Element:
    try:
        return etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise FrameworkError(f"Malformed XML in {part_name or 'part'}: {exc}") from exc


def xml_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def canonical_xml(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", with_comments=True)


def part_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def relationships_part(part_name: str) -> str:
    directory, filename = posixpath.split(part_name)
    return posixpath.join(directory, "_rels", filename + ".rels")


def resolve_target(owner_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner_part), target))


def relative_target(owner_part: str, target_part: str) -> str:
    return posixpath.relpath(target_part, posixpath.dirname(owner_part))


class DocxPackage:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FrameworkError(f"DOCX not found: {self.path}")
        try:
            with zipfile.ZipFile(self.path, "r") as archive:
                self.parts = {name: archive.read(name) for name in archive.namelist()}
        except (zipfile.BadZipFile, OSError) as exc:
            raise FrameworkError(f"Invalid DOCX package: {self.path}: {exc}") from exc
        if "word/document.xml" not in self.parts:
            raise FrameworkError(f"DOCX is missing word/document.xml: {self.path}")

    def xml(self, name: str) -> etree._Element:
        if name not in self.parts:
            raise FrameworkError(f"Missing package part: {name}")
        return parse_xml(self.parts[name], name)

    def optional_xml(self, name: str) -> etree._Element | None:
        data = self.parts.get(name)
        return parse_xml(data, name) if data is not None else None

    def document(self) -> etree._Element:
        return self.xml("word/document.xml")

    def body(self) -> etree._Element:
        body = self.document().find("w:body", NS)
        if body is None:
            raise FrameworkError("word/document.xml has no w:body")
        return body

    def clone_parts(self) -> dict[str, bytes]:
        return dict(self.parts)

    def part_inventory(self) -> list[dict[str, object]]:
        return [
            {"path": name, "size": len(data), "sha256": part_hash(data)}
            for name, data in sorted(self.parts.items())
        ]

    def relationship_map(self, owner_part: str) -> dict[str, etree._Element]:
        rel_name = relationships_part(owner_part)
        root = self.optional_xml(rel_name)
        if root is None:
            return {}
        return {str(rel.get("Id")): rel for rel in root.findall("pr:Relationship", NS)}

    def invalid_xml_parts(self) -> list[str]:
        invalid: list[str] = []
        for name, data in self.parts.items():
            if name.endswith((".xml", ".rels")):
                try:
                    etree.fromstring(data)
                except etree.XMLSyntaxError:
                    invalid.append(name)
        return invalid

    def broken_relationships(self) -> list[dict[str, str]]:
        broken: list[dict[str, str]] = []
        for rels_name, data in self.parts.items():
            if not rels_name.endswith(".rels"):
                continue
            root = parse_xml(data, rels_name)
            rels_dir = posixpath.dirname(rels_name)
            owner_dir = posixpath.dirname(rels_dir)
            rel_filename = posixpath.basename(rels_name)
            owner_filename = rel_filename[:-5]
            owner_part = posixpath.join(owner_dir, owner_filename)
            if rels_name == "_rels/.rels":
                owner_part = ""
            for rel in root.findall("pr:Relationship", NS):
                if rel.get("TargetMode") == "External":
                    continue
                target = str(rel.get("Target", ""))
                resolved = (
                    target.lstrip("/")
                    if owner_part == ""
                    else resolve_target(owner_part, target)
                )
                if resolved not in self.parts:
                    broken.append(
                        {
                            "relationships_part": rels_name,
                            "id": str(rel.get("Id", "")),
                            "target": resolved,
                        }
                    )
        return broken


def deep_copy_children(elements: Iterable[etree._Element]) -> list[etree._Element]:
    return [deepcopy(element) for element in elements]


def write_new_docx(output: Path, parts: dict[str, bytes]) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise IntegrityError(f"Refusing to overwrite existing DOCX: {output}")
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(parts.items()):
                archive.writestr(name, data)
        with zipfile.ZipFile(temporary, "r") as check:
            bad = check.testzip()
            if bad:
                raise FrameworkError(f"Generated DOCX failed ZIP validation at {bad}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
