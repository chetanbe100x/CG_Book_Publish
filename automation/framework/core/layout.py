from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import FrameworkError


TWIPS_PER_MM = 1440.0 / 25.4


def mm_to_twips(value: float) -> int:
    return round(float(value) * TWIPS_PER_MM)


@dataclass(frozen=True)
class StyleSpec:
    font_role: str
    size_points: float
    bold: bool = False
    italic: bool = False
    color: str = "181818"
    alignment: str = "left"
    space_before_points: float = 0.0
    space_after_points: float = 0.0
    line_spacing: float = 1.0
    left_indent_twips: int = 0


@dataclass(frozen=True)
class PageGeometry:
    width_mm: float
    height_mm: float
    live_body_width_mm: float
    inside_margin_mm: float
    outside_margin_mm: float
    top_content_mm: float
    bottom_content_mm: float
    first_content_side: str

    def margins_for_page(self, page_index: int) -> tuple[float, float]:
        first_is_recto = self.first_content_side == "recto"
        is_recto = (page_index % 2 == 0) == first_is_recto
        if is_recto:
            return self.inside_margin_mm, self.outside_margin_mm
        return self.outside_margin_mm, self.inside_margin_mm


@dataclass(frozen=True)
class OptionGeometry:
    table_indent_twips: int
    table_width_twips: int
    two_column_widths_twips: tuple[int, int]
    four_inline_widths_twips: tuple[int, int, int, int]
    cell_margin_top_twips: int
    cell_margin_right_twips: int
    cell_margin_bottom_twips: int
    cell_margin_left_twips: int
    row_space_after_points: float
    max_two_column_visual_units: float
    max_four_inline_visual_units: float


@dataclass(frozen=True)
class AnswerSpace:
    default_pitch_points: float
    generous_pitch_points: float
    line_counts_by_marks: dict[int, int]
    border_color: str
    border_size_eighth_points: int
    border_space_points: int


@dataclass(frozen=True)
class ImagePolicy:
    formula_min_dpi: float
    technical_min_dpi: float
    decorative_min_dpi: float


@dataclass(frozen=True)
class PrintLayoutProfile:
    name: str
    page: PageGeometry
    styles: dict[str, StyleSpec]
    options: OptionGeometry
    answer_space: AnswerSpace
    images: ImagePolicy
    inline_math_points: float

    def style(self, role: str) -> StyleSpec:
        try:
            return self.styles[role]
        except KeyError as exc:
            raise FrameworkError(
                f"Print layout profile {self.name!r} has no style role {role!r}"
            ) from exc


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FrameworkError(f"{label} must be an object")
    return value


def _number(value: Any, label: str, *, positive: bool = True) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FrameworkError(f"{label} must be numeric")
    result = float(value)
    if positive and result <= 0:
        raise FrameworkError(f"{label} must be positive")
    return result


def _integer(value: Any, label: str, *, positive: bool = True) -> int:
    result = int(_number(value, label, positive=positive))
    if result != value:
        raise FrameworkError(f"{label} must be an integer")
    return result


def _style(value: Any, label: str) -> StyleSpec:
    data = _mapping(value, label)
    color = str(data.get("color", "181818")).lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", color):
        raise FrameworkError(f"{label}.color must be a six-digit RGB value")
    alignment = str(data.get("alignment", "left"))
    if alignment not in {"left", "center", "right", "justify"}:
        raise FrameworkError(f"{label}.alignment is unsupported: {alignment}")
    return StyleSpec(
        font_role=str(data["font_role"]),
        size_points=_number(data["size_points"], f"{label}.size_points"),
        bold=bool(data.get("bold", False)),
        italic=bool(data.get("italic", False)),
        color=color,
        alignment=alignment,
        space_before_points=_number(
            data.get("space_before_points", 0),
            f"{label}.space_before_points",
            positive=False,
        ),
        space_after_points=_number(
            data.get("space_after_points", 0),
            f"{label}.space_after_points",
            positive=False,
        ),
        line_spacing=_number(data.get("line_spacing", 1.0), f"{label}.line_spacing"),
        left_indent_twips=mm_to_twips(
            _number(
                data.get("left_indent_mm", 0),
                f"{label}.left_indent_mm",
                positive=False,
            )
        ),
    )


def _legacy_layout(profile_name: str) -> dict[str, Any]:
    """Return conservative explicit tokens for profiles not yet print-calibrated."""
    return {
        "page": {
            "width_mm": 210.0,
            "height_mm": 297.0,
            "live_body_width_mm": 159.2,
            "inside_margin_mm": 25.4,
            "outside_margin_mm": 25.4,
            "top_content_mm": 25.4,
            "bottom_content_mm": 271.0,
            "first_content_side": "recto",
        },
        "styles": {
            "body": {"font_role": "latin", "size_points": 10.5, "space_after_points": 2, "line_spacing": 1.05},
            "hindi": {"font_role": "hindi", "size_points": 11.5, "space_after_points": 2, "line_spacing": 1.05},
            "english": {"font_role": "latin", "size_points": 10.5, "color": "64748B", "space_after_points": 2, "line_spacing": 1.05, "left_indent_mm": 4.5},
            "question": {"font_role": "hindi", "size_points": 11.5, "space_after_points": 2, "line_spacing": 1.05},
            "question_label": {"font_role": "latin", "size_points": 11.5, "bold": True, "color": "168873"},
            "unit": {"font_role": "latin", "size_points": 14, "bold": True, "alignment": "center", "space_after_points": 4},
            "chapter": {"font_role": "latin", "size_points": 14, "bold": True, "alignment": "center", "space_after_points": 4},
            "question_type": {"font_role": "latin", "size_points": 11.5, "bold": True, "alignment": "center", "space_before_points": 5, "space_after_points": 5},
            "equation": {"font_role": "math", "size_points": 11.5, "alignment": "center", "space_after_points": 3},
            "option": {"font_role": "math", "size_points": 10.5, "space_after_points": 5.5},
            "option_label": {"font_role": "latin", "size_points": 10.5, "bold": True, "color": "168873"},
            "answer_line": {"font_role": "latin", "size_points": 9},
        },
        "inline_math_points": 11.5,
        "options": {
            "table_indent_twips": 0,
            "table_width_twips": 8640,
            "two_column_widths_twips": [4320, 4320],
            "four_inline_widths_twips": [2160, 2160, 2160, 2160],
            "cell_margins_twips": {"top": 0, "right": 80, "bottom": 0, "left": 80},
            "row_space_after_points": 5.5,
            "max_two_column_visual_units": 52,
            "max_four_inline_visual_units": 18,
        },
        "answer_space": {
            "default_pitch_points": 30.5,
            "generous_pitch_points": 34.5,
            "line_counts_by_marks": {"3": 7, "4": 9, "5": 11},
            "border_color": "B7B7B7",
            "border_size_eighth_points": 4,
            "border_space_points": 1,
        },
        "images": {
            "formula_min_dpi": 300,
            "technical_min_dpi": 300,
            "decorative_min_dpi": 150,
        },
    }


def load_print_layout(profile_name: str) -> PrintLayoutProfile:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile_name):
        raise FrameworkError(f"Invalid subject profile name: {profile_name}")
    profile_path = Path(__file__).resolve().parents[1] / "profiles" / f"{profile_name}.json"
    if not profile_path.is_file():
        raise FrameworkError(f"Subject profile was not found: {profile_path}")
    try:
        root = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrameworkError(f"Invalid subject profile {profile_path}: {exc}") from exc
    print_layout = root.get("print_layout")
    data = _legacy_layout(profile_name) if print_layout is None else _mapping(
        print_layout, f"{profile_name}.print_layout"
    )

    page_data = _mapping(data.get("page"), f"{profile_name}.print_layout.page")
    first_side = str(page_data.get("first_content_side", "recto"))
    if first_side not in {"recto", "verso"}:
        raise FrameworkError("first_content_side must be recto or verso")
    page = PageGeometry(
        width_mm=_number(page_data["width_mm"], "page.width_mm"),
        height_mm=_number(page_data["height_mm"], "page.height_mm"),
        live_body_width_mm=_number(page_data["live_body_width_mm"], "page.live_body_width_mm"),
        inside_margin_mm=_number(page_data["inside_margin_mm"], "page.inside_margin_mm"),
        outside_margin_mm=_number(page_data["outside_margin_mm"], "page.outside_margin_mm"),
        top_content_mm=_number(page_data["top_content_mm"], "page.top_content_mm"),
        bottom_content_mm=_number(page_data["bottom_content_mm"], "page.bottom_content_mm"),
        first_content_side=first_side,
    )
    if abs(page.width_mm - page.inside_margin_mm - page.outside_margin_mm - page.live_body_width_mm) > 0.2:
        raise FrameworkError("Live body width and inside/outside margins do not fill the page width")

    style_data = _mapping(data.get("styles"), f"{profile_name}.print_layout.styles")
    required_styles = {
        "body", "hindi", "english", "question", "question_label", "unit",
        "chapter", "question_type", "equation", "option", "option_label",
        "answer_line",
    }
    missing_styles = required_styles - set(style_data)
    if missing_styles:
        raise FrameworkError(
            "Print layout is missing style roles: " + ", ".join(sorted(missing_styles))
        )
    styles = {name: _style(value, f"styles.{name}") for name, value in style_data.items()}

    option_data = _mapping(data.get("options"), "print_layout.options")
    two_columns = tuple(
        _integer(value, "options.two_column_widths_twips")
        for value in option_data["two_column_widths_twips"]
    )
    four_columns = tuple(
        _integer(value, "options.four_inline_widths_twips")
        for value in option_data["four_inline_widths_twips"]
    )
    if len(two_columns) != 2 or len(four_columns) != 4:
        raise FrameworkError("Option column grids must contain exactly two and four widths")
    table_width = _integer(option_data["table_width_twips"], "options.table_width_twips")
    if sum(two_columns) != table_width or sum(four_columns) != table_width:
        raise FrameworkError("Option tblW and tblGrid widths must agree")
    margins = _mapping(option_data.get("cell_margins_twips", {}), "options.cell_margins_twips")
    options = OptionGeometry(
        table_indent_twips=_integer(option_data.get("table_indent_twips", 0), "options.table_indent_twips", positive=False),
        table_width_twips=table_width,
        two_column_widths_twips=(two_columns[0], two_columns[1]),
        four_inline_widths_twips=(four_columns[0], four_columns[1], four_columns[2], four_columns[3]),
        cell_margin_top_twips=_integer(margins.get("top", 0), "options.cell_margins_twips.top", positive=False),
        cell_margin_right_twips=_integer(margins.get("right", 0), "options.cell_margins_twips.right", positive=False),
        cell_margin_bottom_twips=_integer(margins.get("bottom", 0), "options.cell_margins_twips.bottom", positive=False),
        cell_margin_left_twips=_integer(margins.get("left", 0), "options.cell_margins_twips.left", positive=False),
        row_space_after_points=_number(option_data["row_space_after_points"], "options.row_space_after_points", positive=False),
        max_two_column_visual_units=_number(option_data["max_two_column_visual_units"], "options.max_two_column_visual_units"),
        max_four_inline_visual_units=_number(option_data["max_four_inline_visual_units"], "options.max_four_inline_visual_units"),
    )

    answer_data = _mapping(data.get("answer_space"), "print_layout.answer_space")
    counts = _mapping(answer_data.get("line_counts_by_marks"), "answer_space.line_counts_by_marks")
    border_color = str(answer_data.get("border_color", "B7B7B7")).lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", border_color):
        raise FrameworkError("answer_space.border_color must be a six-digit RGB value")
    answer_space = AnswerSpace(
        default_pitch_points=_number(answer_data["default_pitch_points"], "answer_space.default_pitch_points"),
        generous_pitch_points=_number(answer_data["generous_pitch_points"], "answer_space.generous_pitch_points"),
        line_counts_by_marks={int(mark): _integer(count, f"answer_space.line_counts_by_marks.{mark}") for mark, count in counts.items()},
        border_color=border_color,
        border_size_eighth_points=_integer(answer_data.get("border_size_eighth_points", 4), "answer_space.border_size_eighth_points"),
        border_space_points=_integer(answer_data.get("border_space_points", 1), "answer_space.border_space_points", positive=False),
    )

    image_data = _mapping(data.get("images"), "print_layout.images")
    images = ImagePolicy(
        formula_min_dpi=_number(image_data["formula_min_dpi"], "images.formula_min_dpi"),
        technical_min_dpi=_number(image_data["technical_min_dpi"], "images.technical_min_dpi"),
        decorative_min_dpi=_number(image_data["decorative_min_dpi"], "images.decorative_min_dpi"),
    )
    return PrintLayoutProfile(
        name=profile_name,
        page=page,
        styles=styles,
        options=options,
        answer_space=answer_space,
        images=images,
        inline_math_points=_number(data["inline_math_points"], "print_layout.inline_math_points"),
    )
