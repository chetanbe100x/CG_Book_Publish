from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..core.models import (
    FrameworkError,
    IntegrityError,
    atomic_json_write,
    sha256_file,
    utc_now,
)


POINTS_PER_MM = 72.0 / 25.4
A4_WIDTH_POINTS = 210.0 * POINTS_PER_MM
A4_HEIGHT_POINTS = 297.0 * POINTS_PER_MM
A4_TOLERANCE_POINTS = 0.5 * POINTS_PER_MM


class WordRenderError(FrameworkError):
    """Raised when the authoritative Microsoft Word render cannot be certified."""

    def __init__(
        self,
        message: str,
        *,
        possible_orphan: bool = False,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.possible_orphan = possible_orphan
        self.stdout = stdout
        self.stderr = stderr


def _powershell_executable() -> Path:
    configured = os.environ.get("POWERSHELL_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    ]
    discovered = shutil.which("powershell.exe") or shutil.which("powershell")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise WordRenderError(
        "Microsoft Word rendering is unavailable because PowerShell was not found"
    )


def _helper_source() -> str:
    # Keep all Word automation in the bounded child process. In particular, this
    # script deliberately never attaches to an existing Word window.
    return r'''param(
    [Parameter(Mandatory=$true)][string]$InputDocx,
    [Parameter(Mandatory=$true)][string]$OutputPdf,
    [Parameter(Mandatory=$true)][string]$OutputJson,
    [Parameter(Mandatory=$true)][string]$BookmarksJson
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 3.0
$word = $null
$document = $null
$sections = @()
$bookmarkPages = [ordered]@{}

try {
    # Windows PowerShell 5.1 preserves a top-level JSON array as one nested
    # System.Object[] when it is wrapped directly with @(...).  Flatten it
    # through the pipeline so each requested bookmark is checked separately.
    $expectedBookmarks = @(($BookmarksJson | ConvertFrom-Json) |
        ForEach-Object { $_ })

    # A new COM server is required; never attach to an interactive Word session.
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try { $word.AutomationSecurity = 3 } catch { }
    try { $word.Options.UpdateLinksAtOpen = $false } catch { }
    try { $word.Options.UpdateFieldsAtPrint = $false } catch { }
    try { $word.Options.UpdateLinksAtPrint = $false } catch { }
    try { $word.Options.SaveNormalPrompt = $false } catch { }
    try { $word.Options.ConfirmConversions = $false } catch { }

    # ConfirmConversions=false, ReadOnly=true, AddToRecentFiles=false.
    $document = $word.Documents.Open($InputDocx, $false, $true, $false)
    try { $document.UpdateStylesOnOpen = $false } catch { }
    $document.Repaginate()

    $pageCount = [int]$document.ComputeStatistics(2)
    for ($index = 1; $index -le $document.Sections.Count; $index++) {
        $section = $document.Sections.Item($index)
        $setup = $section.PageSetup
        $startRange = $section.Range.Duplicate
        $startRange.Collapse(1)
        $sections += [ordered]@{
            index = $index
            start_page = [int]$startRange.Information(3)
            end_page = [int]$section.Range.Information(3)
            page_width_points = [double]$setup.PageWidth
            page_height_points = [double]$setup.PageHeight
            orientation = [int]$setup.Orientation
            top_margin_points = [double]$setup.TopMargin
            bottom_margin_points = [double]$setup.BottomMargin
            left_margin_points = [double]$setup.LeftMargin
            right_margin_points = [double]$setup.RightMargin
            header_distance_points = [double]$setup.HeaderDistance
            footer_distance_points = [double]$setup.FooterDistance
            gutter_points = [double]$setup.Gutter
            mirror_margins = [bool]$setup.MirrorMargins
        }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($startRange)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($setup)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($section)
    }

    if ($expectedBookmarks.Count -gt 0) {
        foreach ($bookmarkName in $expectedBookmarks) {
            $name = [string]$bookmarkName
            if ($document.Bookmarks.Exists($name)) {
                $bookmark = $document.Bookmarks.Item($name)
                $bookmarkPages[$name] = [int]$bookmark.Range.Information(3)
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($bookmark)
            }
        }
    } else {
        for ($index = 1; $index -le $document.Bookmarks.Count; $index++) {
            $bookmark = $document.Bookmarks.Item($index)
            $bookmarkPages[[string]$bookmark.Name] = [int]$bookmark.Range.Information(3)
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($bookmark)
        }
    }

    # wdExportFormatPDF=17. Printing/link/field updates were disabled above.
    $document.ExportAsFixedFormat($OutputPdf, 17)

    $result = [ordered]@{
        renderer = "microsoft_word"
        word_version = [string]$word.Version
        page_count = $pageCount
        section_count = [int]$document.Sections.Count
        sections = $sections
        bookmark_pages = $bookmarkPages
    }
    $json = $result | ConvertTo-Json -Depth 8 -Compress
    [IO.File]::WriteAllText(
        $OutputJson,
        $json,
        [Text.UTF8Encoding]::new($false)
    )
}
finally {
    if ($null -ne $document) {
        try { $document.Close(0) } catch { }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) } catch { }
    }
    if ($null -ne $word) {
        try { $word.Quit(0) } catch { }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
'''


def _run_word_helper(
    script: Path,
    *,
    input_docx: Path,
    output_pdf: Path,
    output_json: Path,
    expected_bookmarks: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        str(_powershell_executable()),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-InputDocx",
        str(input_docx),
        "-OutputPdf",
        str(output_pdf),
        "-OutputJson",
        str(output_json),
        "-BookmarksJson",
        json.dumps(list(expected_bookmarks), ensure_ascii=False),
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creation_flags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        # Only terminate the helper process we own. A Word COM server may remain;
        # never kill Word by process name because that could destroy user work.
        process.kill()
        stdout, stderr = process.communicate()
        raise WordRenderError(
            "Microsoft Word rendering timed out; the helper was stopped. "
            "A hidden Word instance may still require manual cleanup.",
            possible_orphan=True,
            stdout=stdout,
            stderr=stderr,
        ) from exc
    if process.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "no diagnostic output"
        raise WordRenderError(
            "Microsoft Word rendering failed closed. Word may be unavailable, "
            f"unlicensed, or unable to open the document: {detail}",
            stdout=stdout,
            stderr=stderr,
        )
    if not output_json.is_file():
        raise WordRenderError(
            "Microsoft Word helper completed without producing its render evidence",
            stdout=stdout,
            stderr=stderr,
        )
    try:
        result = json.loads(output_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WordRenderError(
            f"Microsoft Word helper produced invalid render evidence: {exc}",
            stdout=stdout,
            stderr=stderr,
        ) from exc
    if not isinstance(result, dict):
        raise WordRenderError("Microsoft Word helper evidence is not a JSON object")
    result["stdout"] = stdout
    result["stderr"] = stderr
    return result


def _reset_readonly(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _remove_temp_tree(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path, onexc=lambda function, name, error: (
            _reset_readonly(name), function(name)
        ))
    except TypeError:  # pragma: no cover - Python < 3.12 compatibility
        shutil.rmtree(path, onerror=lambda function, name, error: (
            _reset_readonly(name), function(name)
        ))


def _validate_sections(
    sections: Any,
    *,
    require_a4: bool,
    orientation: str,
) -> list[dict[str, Any]]:
    if orientation not in {"portrait", "landscape"}:
        raise ValueError("orientation must be 'portrait' or 'landscape'")
    if not isinstance(sections, list) or not sections:
        raise WordRenderError("Word reported no section/page geometry evidence")
    expected_orientation = 0 if orientation == "portrait" else 1
    expected_width = A4_WIDTH_POINTS if orientation == "portrait" else A4_HEIGHT_POINTS
    expected_height = A4_HEIGHT_POINTS if orientation == "portrait" else A4_WIDTH_POINTS
    normalized: list[dict[str, Any]] = []
    for position, raw in enumerate(sections, start=1):
        if not isinstance(raw, dict):
            raise WordRenderError(f"Word section {position} evidence is malformed")
        try:
            width = float(raw["page_width_points"])
            height = float(raw["page_height_points"])
            section_orientation = int(raw["orientation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WordRenderError(
                f"Word section {position} has incomplete page geometry"
            ) from exc
        if section_orientation != expected_orientation:
            raise WordRenderError(
                f"Word section {position} orientation is not {orientation}"
            )
        if require_a4 and (
            abs(width - expected_width) > A4_TOLERANCE_POINTS
            or abs(height - expected_height) > A4_TOLERANCE_POINTS
        ):
            raise WordRenderError(
                f"Word section {position} is not A4 within 0.5 mm "
                f"({width:.2f} x {height:.2f} pt)"
            )
        item = dict(raw)
        item["page_width_points"] = width
        item["page_height_points"] = height
        normalized.append(item)
    return normalized


def _validate_bookmarks(
    raw: Any,
    *,
    expected_bookmarks: tuple[str, ...],
    page_count: int,
) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise WordRenderError("Word bookmark page evidence is malformed")
    bookmark_pages: dict[str, int] = {}
    for name, value in raw.items():
        try:
            page = int(value)
        except (TypeError, ValueError) as exc:
            raise WordRenderError(f"Bookmark {name!r} has an invalid page number") from exc
        if page < 1 or page > page_count:
            raise WordRenderError(
                f"Bookmark {name!r} maps outside the rendered document: page {page}"
            )
        bookmark_pages[str(name)] = page
    missing = [name for name in expected_bookmarks if name not in bookmark_pages]
    if missing:
        raise WordRenderError(
            "Word did not find required bookmarks: " + ", ".join(missing)
        )
    return bookmark_pages


def render_with_word(
    document: Path,
    output_dir: Path,
    *,
    expected_page_count: int | None,
    expected_bookmarks: tuple[str, ...] = (),
    require_a4: bool = True,
    orientation: str = "portrait",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Render a DOCX through an isolated Microsoft Word instance.

    The original document is never opened by Word. Word receives a read-only
    temporary copy, and the original hash must remain stable through the render.
    Only a fully validated PDF and its hash-bound manifest are published.
    """
    document = Path(document).resolve()
    output_dir = Path(output_dir).resolve()
    if not document.is_file():
        raise WordRenderError(f"Cannot render missing DOCX: {document}")
    if document.suffix.casefold() not in {".docx", ".docm"}:
        raise WordRenderError(f"Microsoft Word renderer requires DOCX/DOCM: {document}")
    if expected_page_count is not None and expected_page_count < 1:
        raise ValueError("expected_page_count must be positive when provided")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    if len(set(expected_bookmarks)) != len(expected_bookmarks):
        raise ValueError("expected_bookmarks must be unique")

    document_hash_before = sha256_file(document)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / f".word_render_tmp_{uuid.uuid4().hex}"
    temporary.mkdir(parents=False, exist_ok=False)
    copied_document = temporary / document.name
    helper_script = temporary / "word_render_helper.ps1"
    temporary_pdf = temporary / "render.pdf"
    temporary_json = temporary / "word-evidence.json"
    published_pdf = output_dir / f"{document.stem}.word.pdf"
    published_manifest = output_dir / f"{document.stem}.word-render.json"

    try:
        shutil.copy2(document, copied_document)
        copied_hash = sha256_file(copied_document)
        if copied_hash != document_hash_before:
            raise IntegrityError("Read-only Word render copy does not match the input DOCX")
        copied_document.chmod(stat.S_IREAD)
        helper_script.write_text(_helper_source(), encoding="utf-8")

        result = _run_word_helper(
            helper_script,
            input_docx=copied_document,
            output_pdf=temporary_pdf,
            output_json=temporary_json,
            expected_bookmarks=expected_bookmarks,
            timeout_seconds=timeout_seconds,
        )
        if result.get("renderer") != "microsoft_word":
            raise WordRenderError("Word helper reported an unexpected renderer")
        if not temporary_pdf.is_file() or temporary_pdf.stat().st_size == 0:
            raise WordRenderError("Word completed without producing a non-empty PDF")

        try:
            word_page_count = int(result["page_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WordRenderError("Word did not report a valid page count") from exc
        try:
            pdf_page_count = len(PdfReader(str(temporary_pdf)).pages)
        except Exception as exc:
            raise WordRenderError(f"Word produced an unreadable PDF: {exc}") from exc
        if pdf_page_count != word_page_count:
            raise WordRenderError(
                "Word/PDF page-count mismatch: "
                f"Word reported {word_page_count}, PDF contains {pdf_page_count}"
            )
        if expected_page_count is not None and word_page_count != expected_page_count:
            raise WordRenderError(
                f"Word rendered {word_page_count} pages; expected {expected_page_count}"
            )

        word_version = str(result.get("word_version", "")).strip()
        if not word_version:
            raise WordRenderError("Word did not report its version")
        sections = _validate_sections(
            result.get("sections"),
            require_a4=require_a4,
            orientation=orientation,
        )
        bookmark_pages = _validate_bookmarks(
            result.get("bookmark_pages"),
            expected_bookmarks=expected_bookmarks,
            page_count=word_page_count,
        )

        document_hash_after = sha256_file(document)
        if document_hash_after != document_hash_before:
            raise IntegrityError("Input DOCX changed while Microsoft Word QA was running")
        pdf_hash = sha256_file(temporary_pdf)
        manifest = {
            "schema_version": 1,
            "authoritative": True,
            "renderer": "microsoft_word",
            "rendered_at": utc_now(),
            "document": str(document),
            "document_sha256": document_hash_before,
            "document_sha256_after": document_hash_after,
            "render_copy_sha256": copied_hash,
            "render_pdf": str(published_pdf),
            "render_pdf_sha256": pdf_hash,
            "word_version": word_version,
            "page_count": word_page_count,
            "pdf_page_count": pdf_page_count,
            "section_count": len(sections),
            "sections": sections,
            "bookmark_pages": bookmark_pages,
            "requirements": {
                "expected_page_count": expected_page_count,
                "expected_bookmarks": list(expected_bookmarks),
                "require_a4": bool(require_a4),
                "orientation": orientation,
            },
            "passed": True,
        }

        manifest_temp = temporary / "render-manifest.json"
        atomic_json_write(manifest_temp, manifest)
        os.replace(temporary_pdf, published_pdf)
        os.replace(manifest_temp, published_manifest)
        return {"manifest": str(published_manifest), **manifest}
    finally:
        integrity_error: IntegrityError | None = None
        try:
            if not document.is_file():
                integrity_error = IntegrityError(
                    "Input DOCX disappeared while Microsoft Word QA was running"
                )
            elif sha256_file(document) != document_hash_before:
                integrity_error = IntegrityError(
                    "Input DOCX changed while Microsoft Word QA was running"
                )
        except OSError as exc:
            integrity_error = IntegrityError(f"Could not re-hash input DOCX: {exc}")
        _remove_temp_tree(temporary)

        if integrity_error is not None:
            raise integrity_error


def validate_word_render_manifest(
    document: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate that a Word render manifest still matches its DOCX and PDF."""
    document = Path(document).resolve()
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise IntegrityError(f"Word render manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"Word render manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise IntegrityError("Word render manifest is not a JSON object")
    if manifest.get("renderer") != "microsoft_word" or not manifest.get("authoritative"):
        raise IntegrityError("QA approval requires an authoritative Microsoft Word render")
    if not manifest.get("passed"):
        raise IntegrityError("Microsoft Word render manifest is not marked as passed")
    expected_document_hash = manifest.get("document_sha256")
    if (
        not isinstance(expected_document_hash, str)
        or sha256_file(document) != expected_document_hash
    ):
        raise IntegrityError("DOCX changed after the Microsoft Word render")
    raw_pdf = manifest.get("render_pdf")
    if not isinstance(raw_pdf, str) or not raw_pdf:
        raise IntegrityError("Word render manifest does not identify its PDF")
    render_pdf = Path(raw_pdf)
    if not render_pdf.is_absolute():
        render_pdf = (manifest_path.parent / render_pdf).resolve()
    if not render_pdf.is_file():
        raise IntegrityError(f"Word render PDF is missing: {render_pdf}")
    expected_pdf_hash = manifest.get("render_pdf_sha256")
    if not isinstance(expected_pdf_hash, str) or sha256_file(render_pdf) != expected_pdf_hash:
        raise IntegrityError("Word render PDF changed after rendering")
    return manifest
