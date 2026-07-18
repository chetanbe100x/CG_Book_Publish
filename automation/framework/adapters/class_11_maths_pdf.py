from __future__ import annotations

from collections.abc import Iterator
import sys
from pathlib import Path
from typing import Any

from pdf2image import convert_from_path

from ..capabilities.images_vml import DPI_ROUNDING_TOLERANCE
from ..core.models import FrameworkError, JobConfig


def _poppler_path() -> Path:
    dependencies = Path(sys.executable).resolve().parent.parent
    candidate = dependencies / "native" / "poppler" / "Library" / "bin"
    if (candidate / "pdftoppm.exe").is_file():
        return candidate
    fallback = Path(r"C:\Users\chetan\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin")
    if (fallback / "pdftoppm.exe").is_file():
        return fallback
    raise FrameworkError(f"Bundled Poppler was not found at {candidate} or {fallback}")


def _prepare_crop(
    job: JobConfig,
    *,
    source_page: int,
    bbox_points: list[float],
    destination: Path,
    dpi: int = 300,
) -> tuple[int, int]:
    if destination.is_file():
        from PIL import Image

        with Image.open(destination) as existing:
            return existing.size
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
    cropped = image.crop((left, top, right, bottom))
    cropped.save(destination, dpi=(dpi, dpi))
    return cropped.size
TECHNICAL_FIGURES: dict[int, dict[str, Any]] = {
    3: {
        "question_id": "q-p003-002",
        "path": "figures-v1/page-003-venn.png",
        "bbox": [190.5, 484.5, 415.5, 635.2],
        "alt_text": (
            "Three-set Venn diagram in a rectangle; the overlap of A and B is shaded."
        ),
    },
    19: {
        "question_id": "q-p019-001",
        "path": "figures-v1/page-019-mapping.png",
        "bbox": [190.5, 196.5, 415.5, 351.7],
        "alt_text": "Arrow mapping diagram from set P to set Q.",
    },
    65: {
        "question_id": "q-p065-001",
        "path": "figures-v1/page-065-population-graph.png",
        "bbox": [190.5, 196.5, 415.5, 365.3],
        "alt_text": "Population against year graph containing line AB.",
    },
    94: {
        "question_id": "q-p094-002",
        "path": "figures-v1/page-094-data-table.png",
        "bbox": [179.2, 363.7, 404.2, 401.2],
        "alt_text": "Source data table for the statistics question.",
    },
    95: {
        "question_id": "q-p095-001",
        "path": "figures-v1/page-095-data-table.png",
        "bbox": [190.5, 175.5, 415.5, 204.8],
        "alt_text": "Source data table for the statistics question.",
    },
    96: {
        "question_id": "q-p096-001",
        "path": "figures-v1/page-096-data-table.png",
        "bbox": [179.2, 159.0, 404.2, 191.2],
        "alt_text": "Source data table for the statistics question.",
    },
    97: {
        "question_id": "q-p097-001",
        "path": "figures-v1/page-097-data-table.png",
        "bbox": [190.5, 159.0, 415.5, 187.5],
        "alt_text": "Source data table for the statistics question.",
    },
    98: {
        "question_id": "q-p098-001",
        "path": "figures-v1/page-098-subject-statistics-table.png",
        "bbox": [179.2, 234.7, 404.2, 284.9],
        "alt_text": (
            "Table of mean and standard deviation for Mathematics, Physics, "
            "and Chemistry."
        ),
    },
}

ANSWER_CANVASES: dict[int, tuple[dict[str, Any], ...]] = {
    19: (
        {
            "question_id": "q-p019-002",
            "bbox": [62.2, 571.5, 544.4, 687.0],
            "canvas_type": "graph",
        },
    ),
    65: (
        {
            "question_id": "q-p065-001",
            "bbox": [62.2, 375.7, 544.4, 690.7],
            "canvas_type": "blank",
        },
    ),
    81: (
        {
            "question_id": "q-p081-001",
            "bbox": [62.2, 201.0, 544.4, 687.0],
            "canvas_type": "blank",
        },
    ),
}

QUESTION_TEXT_OVERRIDES: dict[tuple[int, str], dict[str, str]] = {
    (19, "q-p019-001"): {
        "english": (
            "Show the following figure and write the relation between P and Q "
            "in both set-builder form and roster form."
        ),
    },
    (65, "q-p065-001"): {
        "hindi": (
            "\u091c\u0928\u0938\u0902\u0916\u094d\u092f\u093e \u0914\u0930 \u0935\u0930\u094d\u0937 \u0915\u0947 \u0928\u093f\u092e\u094d\u0928\u0932\u093f\u0916\u093f\u0924 \u0932\u0947\u0916\u093e\u091a\u093f\u0924\u094d\u0930 \u0915\u0940 \u0938\u0939\u093e\u092f\u0924\u093e \u0938\u0947 \u0930\u0947\u0916\u093e AB \u0915\u0940 \u0922\u093e\u0932 \u091c\u094d\u091e\u093e\u0924 \u0915\u0940\u091c\u093f\u090f \u0914\u0930 \u0907\u0938\u0915\u0947 \u092a\u094d\u0930\u092f\u094b\u0917 \u0938\u0947 \u092c\u0924\u093e\u0907\u090f \u0915\u093f \u0935\u0930\u094d\u0937 2010 \u092e\u0947\u0902 \u091c\u0928\u0938\u0902\u0916\u094d\u092f\u093e \u0915\u093f\u0924\u0928\u0940 \u0939\u094b\u0917\u0940?"
        ),
        "english": (
            "Using the given population and year graph, find the slope of line "
            "AB and use it to predict the population in the year 2010."
        ),
    },
    (94, "q-p094-002"): {
        "english": "Find the mean deviation of the given data.",
    },
    (95, "q-p095-001"): {
        "english": (
            "Find the mean deviation and coefficient of mean deviation of the "
            "following distribution."
        ),
    },
    (96, "q-p096-001"): {
        "english": "Find the standard deviation of the given data.",
    },
    (97, "q-p097-001"): {
        "english": (
            "Find the standard deviation of the following frequency "
            "distribution."
        ),
    },
    (98, "q-p098-001"): {
        "english": (
            "The mean and standard deviation of marks obtained by 50 students "
            "in Mathematics, Physics, and Chemistry are given below. Which "
            "of the three subjects shows the highest variability in marks and "
            "which shows the lowest?"
        ),
    },
}
def _formula_run(
    path: str,
    bbox: list[float],
    alt_text: str,
) -> dict[str, Any]:
    left, _, right, _ = (float(value) for value in bbox)
    return {
        "language": "math",
        "formula_image": {
            "path": path,
            "crop_bbox_points": list(bbox),
            "alt_text": alt_text,
            "width_inches": (right - left) / 72.0,
            "crop_dpi": 400,
            "minimum_effective_dpi": 300,
            "effective_dpi": 400,
        },
    }


QUESTION_RUN_OVERRIDES: dict[tuple[int, str], dict[str, list[dict[str, Any]]]] = {
    (14, "q-p014-003"): {
        "hindi_runs": [
            {"text": "\u092b\u0932\u0928 ", "language": "hindi"},
            _formula_run(
                "formulas-v1/page-014-q3-hindi.png",
                [112.5, 489.0, 200.0, 516.0],
                "f of x equals one divided by three x plus two",
            ),
            {
                "text": " \u0915\u093e \u092a\u094d\u0930\u093e\u0902\u0924 "
                "\u0939\u094b\u0917\u093e\u0964",
                "language": "hindi",
            },
        ],
        "english_runs": [
            {
                "text": "The domain of the function ",
                "language": "latin",
            },
            _formula_run(
                "formulas-v1/page-014-q3-english.png",
                [239.0, 514.0, 314.5, 536.5],
                "f of x equals one divided by three x plus two",
            ),
            {"text": " is?", "language": "latin"},
        ],
    },
    (14, "q-p014-004"): {
        "hindi_runs": [
            {"text": "\u092f\u0926\u093f ", "language": "hindi"},
            _formula_run(
                "formulas-v1/page-014-q4-function-hindi.png",
                [104.0, 616.5, 177.0, 641.0],
                "f of x equals x squared",
            ),
            {
                "text": " \u0939\u094b \u0924\u092c ",
                "language": "hindi",
            },
            _formula_run(
                "formulas-v1/page-014-q4-quotient-hindi.png",
                [214.0, 616.0, 279.5, 646.0],
                "the difference quotient at 1.1 and 1",
            ),
            {
                "text": " \u0915\u093e \u092e\u093e\u0928 "
                "\u0939\u094b\u0917\u093e\u0964",
                "language": "hindi",
            },
        ],
        "english_runs": [
            {"text": "If ", "language": "latin"},
            _formula_run(
                "formulas-v1/page-014-q4-function-english.png",
                [93.0, 645.0, 156.0, 665.0],
                "f of x equals x squared",
            ),
            {"text": " then value of ", "language": "latin"},
            _formula_run(
                "formulas-v1/page-014-q4-quotient-english.png",
                [238.0, 641.5, 293.5, 668.0],
                "the difference quotient at 1.1 and 1",
            ),
            {"text": ".", "language": "latin"},
        ],
    },
    (47, "q-p047-001"): {
        "hindi_runs": [
            {"text": "\u092f\u0926\u093f ", "language": "hindi"},
            {
                "text": "2n",
                "language": "math",
                "superscript": True,
            },
            {"text": "C", "language": "math"},
            {"text": "3", "language": "math", "subscript": True},
            {"text": " : ", "language": "math"},
            {"text": "n", "language": "math", "superscript": True},
            {"text": "C", "language": "math"},
            {"text": "3", "language": "math", "subscript": True},
            {"text": " = 11 : 1", "language": "math"},
            {
                "text": " \u0939\u094b \u0924\u094b n \u0915\u093e "
                "\u092e\u093e\u0928 \u091c\u094d\u091e\u093e\u0924 "
                "\u0915\u0930\u0947\u0964",
                "language": "hindi",
            },
        ],
        "english_runs": [
            {"text": "If ", "language": "latin"},
            {
                "text": "2n",
                "language": "math",
                "superscript": True,
            },
            {"text": "C", "language": "math"},
            {"text": "3", "language": "math", "subscript": True},
            {"text": " : ", "language": "math"},
            {"text": "n", "language": "math", "superscript": True},
            {"text": "C", "language": "math"},
            {"text": "3", "language": "math", "subscript": True},
            {
                "text": " = 11 : 1, find the value of n.",
                "language": "latin",
            },
        ],
    },
    (104, "q-p104-001"): {
        "hindi_runs": [
            {"text": "\u092f\u0926\u093f ", "language": "hindi"},
            _formula_run(
                "formulas-v1/page-104-q16-givens-hindi.png",
                [72.0, 108.0, 224.0, 136.0],
                "P of A equals one fourth and P of B equals one half",
            ),
            {"text": " \u0924\u092c ", "language": "hindi"},
            _formula_run(
                "formulas-v1/page-104-q16-result-hindi.png",
                [246.0, 108.0, 458.0, 136.0],
                "P of E intersection F equals one eighth; find P of E union F",
            ),
        ],
        "english_runs": [
            {"text": "If ", "language": "latin"},
            _formula_run(
                "formulas-v1/page-104-q16-givens-english.png",
                [61.0, 133.5, 191.5, 157.0],
                "P of A equals one fourth and P of B equals one half",
            ),
            {"text": " then ", "language": "latin"},
            _formula_run(
                "formulas-v1/page-104-q16-result-english.png",
                [223.5, 133.5, 405.0, 157.0],
                "P of E intersection F equals one eighth; find P of E union F",
            ),
        ],
    },
}

OPTION_FORMULA_OVERRIDES: dict[tuple[int, str, str], dict[str, Any]] = {
    (14, "q-p014-003", "A"): _formula_run(
        "formulas-v1/page-014-q3-option-a.png",
        [95.0, 547.0, 150.0, 571.0],
        "R minus the set containing two thirds",
    )["formula_image"],
    (14, "q-p014-003", "C"): _formula_run(
        "formulas-v1/page-014-q3-option-c.png",
        [95.0, 578.0, 162.0, 602.0],
        "R minus the set containing negative two thirds",
    )["formula_image"],
}



def _question_index(blocks: list[dict[str, Any]], question_id: str) -> int:
    for index, block in enumerate(blocks):
        if block.get("kind") == "question" and block.get("question_id") == question_id:
            return index
    raise FrameworkError(
        f"Class 11 Maths adapter could not find structured question {question_id}"
    )


def _insert_question_attachment(
    blocks: list[dict[str, Any]],
    question_id: str,
    attachment: dict[str, Any],
) -> None:
    key = (attachment.get("kind"), attachment.get("path"), question_id)
    for block in blocks:
        existing = (block.get("kind"), block.get("path"), block.get("for_question"))
        if existing == key:
            return
    insert_at = _question_index(blocks, question_id) + 1
    before_answer_space = attachment.get("kind") in {"figure", "formula_image"}
    while (
        insert_at < len(blocks)
        and blocks[insert_at].get("for_question") == question_id
        and not (
            before_answer_space
            and blocks[insert_at].get("kind") in {"answer_lines", "answer_canvas"}
        )
    ):
        insert_at += 1
    blocks.insert(insert_at, attachment)


def _enrich_manifest(job: JobConfig, manifest: dict[str, Any]) -> None:
    source_name = job.source.name
    for page in manifest["pages"]:
        page_number = int(page["source_page"])
        blocks = page["blocks"]
        if page_number == 3:
            blocks[:] = [
                block
                for block in blocks
                if not (
                    block.get("kind") == "paragraph"
                    and str(block.get("text", "")).strip() == "A B C"
                )
            ]
            for block in blocks:
                if (
                    block.get("kind") == "options"
                    and block.get("for_question") == "q-p003-002"
                ):
                    for item in block.get("items", []):
                        if str(item.get("label", "")) == "D":
                            item["text"] = (
                                str(item.get("text", ""))
                                .removesuffix(" A B C")
                                .rstrip()
                            )
        for block in blocks:
            if block.get("kind") != "question":
                continue
            question_id = str(block.get("question_id", ""))
            override = QUESTION_TEXT_OVERRIDES.get((page_number, question_id))
            if override:
                block.update(override)
                if "hindi" in override:
                    block.pop("hindi_runs", None)
                if "english" in override:
                    block.pop("english_runs", None)
            run_override = QUESTION_RUN_OVERRIDES.get((page_number, question_id))
            if run_override:
                block.update(run_override)


        for block in blocks:
            if block.get("kind") != "options":
                continue
            question_id = str(block.get("for_question", ""))
            for item in block.get("items", []):
                key = (page_number, question_id, str(item.get("label", "")))
                formula = OPTION_FORMULA_OVERRIDES.get(key)
                if formula:
                    item["formula_image"] = dict(formula)
                    item.pop("runs", None)
                    item.pop("text", None)

        figure = TECHNICAL_FIGURES.get(page_number)
        if figure:
            source_id = f"{source_name}:p{page_number:03d}"
            _insert_question_attachment(
                blocks,
                str(figure["question_id"]),
                {
                    "kind": "figure",
                    "path": str(figure["path"]),
                    "crop_bbox_points": list(figure["bbox"]),
                    "width_inches": 3.125,
                    "crop_dpi": 300,
                    "minimum_effective_dpi": 300,
                    "alt_text": str(figure["alt_text"]),
                    "image_role": "technical",
                    "for_question": str(figure["question_id"]),
                    "source_ids": [source_id],
                    "confidence": "high",
                },
            )

        for canvas in ANSWER_CANVASES.get(page_number, ()):
            source_id = f"{source_name}:p{page_number:03d}"
            left, top, right, bottom = (
                float(value) for value in canvas["bbox"]
            )
            _insert_question_attachment(
                blocks,
                str(canvas["question_id"]),
                {
                    "kind": "answer_canvas",
                    "canvas_type": str(canvas["canvas_type"]),
                    "height_points": bottom - top,
                    "width_points": right - left,
                    "border": True,
                    "for_question": str(canvas["question_id"]),
                    "source_bbox_points": [left, top, right, bottom],
                    "source_detected": True,
                    "source_ids": [source_id],
                    "confidence": "high",
                },
            )



def _formula_images_from_runs(
    container: dict[str, Any],
    fields: tuple[str, ...],
    *,
    context: str,
) -> Iterator[dict[str, Any]]:
    for field in fields:
        runs = container.get(field)
        if runs is None:
            continue
        if not isinstance(runs, list):
            raise FrameworkError(f"{context}.{field} must be an array")
        for run_index, run in enumerate(runs, start=1):
            if not isinstance(run, dict):
                raise FrameworkError(
                    f"{context}.{field} run {run_index} must be an object"
                )
            formula = run.get("formula_image")
            if formula is None:
                continue
            if not isinstance(formula, dict):
                raise FrameworkError(
                    f"{context}.{field} run {run_index}.formula_image must be an object"
                )
            yield formula


def _page_images(page: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for block_index, block in enumerate(page["blocks"], start=1):
        if not isinstance(block, dict):
            raise FrameworkError(f"Page block {block_index} must be an object")
        kind = str(block.get("kind", ""))
        if kind in {"figure", "formula_image"}:
            yield kind, block

        context = f"page {page['source_page']} block {block_index}"
        yield from (
            ("formula_image", formula)
            for formula in _formula_images_from_runs(
                block,
                ("runs", "hindi_runs", "english_runs"),
                context=context,
            )
        )
        if kind != "options":
            continue
        items = block.get("items")
        if not isinstance(items, list):
            raise FrameworkError(f"{context}.items must be an array")
        for item_index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise FrameworkError(
                    f"{context} option {item_index} must be an object"
                )
            option_context = f"{context} option {item_index}"
            formula = item.get("formula_image")
            if formula is not None:
                if not isinstance(formula, dict):
                    raise FrameworkError(
                        f"{option_context}.formula_image must be an object"
                    )
                yield "formula_image", formula
            yield from (
                ("formula_image", nested)
                for nested in _formula_images_from_runs(
                    item,
                    ("runs",),
                    context=option_context,
                )
            )


def _prepare_manifest_image(
    job: JobConfig,
    *,
    manifest_dir: Path,
    source_page: int,
    kind: str,
    image: dict[str, Any],
) -> None:
    if "crop_bbox_points" not in image:
        return
    path_value = str(image.get("path", "")).strip()
    if not path_value:
        raise FrameworkError(f"{kind} on source page {source_page} requires path")
    destination = (manifest_dir / path_value).resolve()
    try:
        destination.relative_to(manifest_dir.resolve())
    except ValueError as exc:
        raise FrameworkError(
            f"Figure output escapes the manifest directory: {destination}"
        ) from exc
    alt_text = str(image.get("alt_text", "")).strip()
    if not alt_text:
        raise FrameworkError(
            f"{kind} on source page {source_page} requires alt_text"
        )
    dpi = int(image.get("crop_dpi", 400 if kind == "formula_image" else 300))
    if dpi <= 0:
        raise FrameworkError(f"{kind} crop_dpi must be positive")
    pixel_width, pixel_height = _prepare_crop(
        job,
        source_page=source_page,
        bbox_points=list(image["crop_bbox_points"]),
        destination=destination,
        dpi=dpi,
    )
    image["rendered_pixels"] = [pixel_width, pixel_height]
    image["rendered_dpi"] = dpi

    width_value = image.get("width_inches", 3.0)
    if (
        not isinstance(width_value, (int, float))
        or isinstance(width_value, bool)
        or float(width_value) <= 0
    ):
        raise FrameworkError(f"{kind}.width_inches must be positive")
    effective_dpi = pixel_width / float(width_value)
    height_value = image.get("height_inches")
    if height_value is not None:
        if (
            not isinstance(height_value, (int, float))
            or isinstance(height_value, bool)
            or float(height_value) <= 0
        ):
            raise FrameworkError(f"{kind}.height_inches must be positive")
        effective_dpi = min(effective_dpi, pixel_height / float(height_value))
    image["effective_dpi"] = round(effective_dpi, 2)
    minimum = float(image.get("minimum_effective_dpi", 300))
    if minimum <= 0:
        raise FrameworkError(f"{kind}.minimum_effective_dpi must be positive")
    if effective_dpi + DPI_ROUNDING_TOLERANCE < minimum:
        raise FrameworkError(
            f"{kind} on source page {source_page} has only "
            f"{effective_dpi:.0f} effective DPI; minimum is {minimum:.0f}"
        )


def prepare(job: JobConfig, manifest: dict[str, Any]) -> None:
    assert job.content_manifest is not None
    manifest_dir = job.content_manifest.parent
    _enrich_manifest(job, manifest)
    for page in manifest["pages"]:
        source_page = int(page["source_page"])
        for kind, image in _page_images(page):
            _prepare_manifest_image(
                job,
                manifest_dir=manifest_dir,
                source_page=source_page,
                kind=kind,
                image=image,
            )
