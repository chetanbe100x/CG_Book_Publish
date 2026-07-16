from __future__ import annotations

import re
import sys
from pathlib import Path

from lxml import etree

from ..core.package import NS, W


def referenced_fonts(root: etree._Element) -> list[str]:
    fonts: set[str] = set()
    for element in root.findall(".//w:rFonts", NS):
        for name in ("ascii", "hAnsi", "eastAsia", "cs"):
            value = element.get(W + name)
            if value and not value.startswith("+"):
                fonts.add(value.strip())
    return sorted(fonts, key=str.casefold)


def referenced_sizes(root: etree._Element) -> list[float]:
    sizes: set[float] = set()
    for element in root.findall(".//w:sz", NS) + root.findall(".//w:szCs", NS):
        value = element.get(W + "val")
        if value and value.isdigit():
            sizes.add(int(value) / 2)
    return sorted(sizes)


def installed_font_names() -> set[str]:
    names: set[str] = set()
    if sys.platform == "win32":
        try:
            import winreg

            locations = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            ]
            for hive, key_name in locations:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        index = 0
                        while True:
                            try:
                                display_name, _, _ = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            cleaned = re.sub(r"\s*\([^)]*(TrueType|OpenType)[^)]*\)\s*$", "", display_name, flags=re.I)
                            for item in cleaned.split(" & "):
                                names.add(item.strip().casefold())
                            index += 1
                except OSError:
                    continue
        except ImportError:
            pass
        font_dir = Path(r"C:\Windows\Fonts")
        if font_dir.is_dir():
            names.update(path.stem.casefold() for path in font_dir.iterdir() if path.is_file())
    return names


def missing_fonts(fonts: list[str], explicit_required: tuple[str, ...] = ()) -> list[str]:
    installed = installed_font_names()
    if not installed:
        return []
    generic = {"symbol", "wingdings", "webdings", "times new roman", "arial", "calibri", "cambria math"}
    required = set(fonts) | set(explicit_required)
    missing = []
    for font in sorted(required, key=str.casefold):
        key = font.casefold()
        if key in installed or key in generic:
            continue
        if any(key in candidate or candidate in key for candidate in installed if len(candidate) > 4):
            continue
        missing.append(font)
    return missing
