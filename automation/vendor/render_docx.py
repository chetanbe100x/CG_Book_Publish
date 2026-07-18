"""Windows-safe wrapper around the canonical document renderer.

The upstream helper is retained beside this file as render_docx_upstream.py.
This wrapper keeps its DOCX -> PDF -> PNG contract while fixing Windows file
URIs and resolving the bundled Poppler executables directly.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pdf2image import convert_from_path

from render_docx_upstream import calc_dpi_via_ooxml_docx


def soffice_path() -> Path:
    configured = os.environ.get("SOFFICE_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("LibreOffice soffice executable was not found")


def poppler_path() -> Path:
    configured = os.environ.get("CODEX_POPPLER_PATH")
    if configured and Path(configured).is_dir():
        return Path(configured)
    dependencies = Path(sys.executable).resolve().parent.parent
    candidate = dependencies / "native" / "poppler" / "Library" / "bin"
    if (candidate / "pdftoppm.exe").is_file():
        return candidate
    fallback = Path(r"C:\Users\chetan\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin")
    if (fallback / "pdftoppm.exe").is_file():
        return fallback
    raise FileNotFoundError(f"Bundled Poppler was not found at {candidate} or {fallback}")


def render(input_path: Path, output_dir: Path, dpi: int, emit_pdf: bool, verbose: bool) -> list[Path]:
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="soffice_profile_") as profile_name:
        with tempfile.TemporaryDirectory(prefix="soffice_convert_") as conversion_name:
            profile = Path(profile_name).resolve()
            conversion = Path(conversion_name).resolve()
            environment = os.environ.copy()
            environment["HOME"] = str(profile)
            command = [
                str(soffice_path()),
                "-env:UserInstallation=" + profile.as_uri(),
                "--invisible",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(conversion),
                str(input_path),
            ]
            process = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                check=False,
            )
            if verbose:
                print("[render_docx] $ " + " ".join(command))
                if process.stdout:
                    print(process.stdout)
                if process.stderr:
                    print(process.stderr, file=sys.stderr)
            pdf = conversion / f"{input_path.stem}.pdf"
            if process.returncode != 0 or not pdf.is_file() or pdf.stat().st_size == 0:
                raise RuntimeError(
                    f"LibreOffice PDF conversion failed ({process.returncode})\n"
                    f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
                )
            if emit_pdf:
                shutil.copy2(pdf, output_dir / pdf.name)
            generated = convert_from_path(
                str(pdf),
                dpi=dpi,
                fmt="png",
                thread_count=8,
                output_folder=str(output_dir),
                paths_only=True,
                output_file="page",
                poppler_path=str(poppler_path()),
            )
    pages: list[tuple[int, Path]] = []
    for generated_path in generated:
        source = Path(generated_path)
        page_number = int(source.stem.split("-")[-1])
        destination = output_dir / f"page-{page_number}.png"
        os.replace(source, destination)
        pages.append((page_number, destination))
    pages.sort(key=lambda item: item[0])
    return [path for _, path in pages]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render DOCX to page PNGs")
    parser.add_argument("input_path")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--dpi", type=int)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=2200)
    parser.add_argument("--emit_pdf", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    input_path = Path(args.input_path)
    dpi = args.dpi or calc_dpi_via_ooxml_docx(str(input_path), args.width, args.height)
    pages = render(input_path, Path(args.output_dir), dpi, args.emit_pdf, args.verbose)
    if not pages:
        raise RuntimeError("No page PNGs were generated")
    print(f"[render_docx] generated {len(pages)} page(s) at {args.output_dir}")


if __name__ == "__main__":
    main()
