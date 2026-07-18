from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image

from ..core.models import FrameworkError
from ..core.package import NS


DPI_ROUNDING_TOLERANCE = 0.5


def inventory(root: etree._Element, media_parts: int = 0) -> dict[str, int]:
    return {
        "drawings": len(root.findall(".//w:drawing", NS)),
        "pictures": len(root.findall(".//pic:pic", NS)),
        "vml_elements": len(root.findall(".//v:*", NS)),
        "vml_shapes": len(root.findall(".//v:shape", NS)),
        "media_parts": media_parts,
    }


def image_pixel_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except (OSError, ValueError) as exc:
        raise FrameworkError(f"Could not inspect image dimensions: {path}: {exc}") from exc


def effective_dpi(
    path: Path,
    *,
    width_inches: float,
    height_inches: float | None = None,
) -> float:
    if width_inches <= 0 or (height_inches is not None and height_inches <= 0):
        raise FrameworkError("Printed image dimensions must be positive")
    width_pixels, height_pixels = image_pixel_size(path)
    horizontal = width_pixels / width_inches
    if height_inches is None:
        return horizontal
    return min(horizontal, height_pixels / height_inches)


def validate_effective_dpi(
    path: Path,
    *,
    width_inches: float,
    minimum_dpi: float,
    height_inches: float | None = None,
) -> float:
    actual = effective_dpi(
        path,
        width_inches=width_inches,
        height_inches=height_inches,
    )
    if actual + DPI_ROUNDING_TOLERANCE < minimum_dpi:
        raise FrameworkError(
            f"Image effective DPI is too low for print: {path} "
            f"({actual:.1f} DPI; requires at least {minimum_dpi:.1f})"
        )
    return actual


def set_picture_alt_text(run: Any, alt_text: str) -> None:
    value = alt_text.strip()
    if not value:
        raise FrameworkError("Figures and formula images require non-empty alt text")
    properties = run._element.find(".//wp:docPr", NS)
    if properties is None:
        raise FrameworkError("Could not locate the picture drawing properties")
    properties.set("descr", value)
    properties.set("title", value)
