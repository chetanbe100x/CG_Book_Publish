from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pdf2image import convert_from_path

from ..core.models import FrameworkError, JobConfig


def _poppler_path() -> Path:
    dependencies = Path(sys.executable).resolve().parent.parent
    candidate = dependencies / "native" / "poppler" / "Library" / "bin"
    if not (candidate / "pdftoppm.exe").is_file():
        raise FrameworkError(f"Bundled Poppler was not found: {candidate}")
    return candidate


def _prepare_crop(
    job: JobConfig,
    *,
    source_page: int,
    bbox_points: list[float],
    destination: Path,
    dpi: int = 240,
) -> None:
    if destination.is_file():
        return
    if len(bbox_points) != 4:
        raise FrameworkError("PDF crop_bbox_points must contain four values")
    rendered = convert_from_path(
        str(job.source),
        first_page=source_page,
        last_page=source_page,
        dpi=dpi,
        fmt="png",
        thread_count=1,
        poppler_path=str(_poppler_path()),
    )
    if len(rendered) != 1:
        raise FrameworkError(f"Could not render PDF page {source_page} for a figure")
    image = rendered[0]
    scale = dpi / 72.0
    left, top, right, bottom = (round(float(value) * scale) for value in bbox_points)
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise FrameworkError(
            f"Figure crop is outside PDF page {source_page}: {bbox_points}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, right, bottom)).save(destination)


def prepare(job: JobConfig, manifest: dict[str, Any]) -> None:
    assert job.content_manifest is not None
    manifest_dir = job.content_manifest.parent
    for page in manifest["pages"]:
        for block in page["blocks"]:
            if block.get("kind") != "figure" or "crop_bbox_points" not in block:
                continue
            destination = (manifest_dir / str(block["path"])).resolve()
            try:
                destination.relative_to(manifest_dir.resolve())
            except ValueError as exc:
                raise FrameworkError(
                    f"Figure output escapes the manifest directory: {destination}"
                ) from exc
            _prepare_crop(
                job,
                source_page=int(page["source_page"]),
                bbox_points=list(block["crop_bbox_points"]),
                destination=destination,
            )
