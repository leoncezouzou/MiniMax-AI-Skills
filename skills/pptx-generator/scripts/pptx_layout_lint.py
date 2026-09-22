#!/usr/bin/env python3
"""Run dependency-free structural and layout checks on a PPTX file.

The linter is intentionally conservative: it fails on geometry and estimated text
overflow that can make a slide unusable, while reporting uncertain text/shape
intersections as warnings for human review.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

EMU_PER_INCH = 914400
POINTS_PER_INCH = 72
DEFAULT_MARGIN_EMU = int(0.1 * EMU_PER_INCH)
DEFAULT_FONT_SIZE_PT = 18.0

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    cx: int
    cy: int

    @property
    def right(self) -> int:
        return self.x + self.cx

    @property
    def bottom(self) -> int:
        return self.y + self.cy

    @property
    def area(self) -> int:
        return max(self.cx, 0) * max(self.cy, 0)

    def intersection_area(self, other: "Bounds") -> int:
        width = max(0, min(self.right, other.right) - max(self.x, other.x))
        height = max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        return width * height

    def contains(self, other: "Bounds") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


@dataclass
class Shape:
    slide: int
    name: str
    kind: str
    bounds: Bounds
    text: str = ""
    font_size_pt: float | None = None
    required_height_pt: float | None = None
    available_height_pt: float | None = None

    @property
    def is_text(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Diagnostic:
    slide: int
    severity: str
    code: str
    message: str
    shape: str | None = None
    related_shape: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def first_child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if local_name(child) == name), None)


def first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element.iter() if local_name(child) == name), None)


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def parse_bounds(node: ET.Element) -> Bounds | None:
    transform = first_descendant(node, "xfrm")
    if transform is None:
        return None
    offset = first_child(transform, "off")
    extent = first_child(transform, "ext")
    if offset is None or extent is None:
        return None
    return Bounds(
        x=parse_int(offset.get("x")),
        y=parse_int(offset.get("y")),
        cx=parse_int(extent.get("cx")),
        cy=parse_int(extent.get("cy")),
    )


def extract_name(node: ET.Element, fallback: str) -> str:
    non_visual = first_descendant(node, "cNvPr")
    return (non_visual.get("name") if non_visual is not None else None) or fallback


def extract_text(node: ET.Element) -> str:
    text_body = first_descendant(node, "txBody")
    if text_body is None:
        return ""

    paragraphs: list[str] = []
    for paragraph in (child for child in text_body if local_name(child) == "p"):
        pieces: list[str] = []
        for item in paragraph.iter():
            item_name = local_name(item)
            if item_name == "t":
                pieces.append(item.text or "")
            elif item_name == "br":
                pieces.append("\n")
        paragraphs.append("".join(pieces))
    return "\n".join(paragraphs)


def extract_font_size(node: ET.Element) -> float:
    for element in node.iter():
        if local_name(element) not in {"rPr", "defRPr", "endParaRPr"}:
            continue
        raw_size = element.get("sz")
        if raw_size is not None:
            size = parse_int(raw_size)
            if size > 0:
                return size / 100.0
    return DEFAULT_FONT_SIZE_PT


def extract_margins(node: ET.Element) -> tuple[int, int, int, int]:
    body = first_descendant(node, "bodyPr")
    if body is None:
        return (DEFAULT_MARGIN_EMU,) * 4
    return tuple(
        parse_int(body.get(attribute), DEFAULT_MARGIN_EMU)
        for attribute in ("lIns", "rIns", "tIns", "bIns")
    )  # type: ignore[return-value]


def char_width_pt(character: str, font_size_pt: float) -> float:
    if character == "\t":
        return font_size_pt * 2.2
    if character.isspace():
        return font_size_pt * 0.28
    if ord(character) > 0x2E80:
        return font_size_pt
    if character in ",.;:!?|()[]{}'\"`":
        return font_size_pt * 0.35
    return font_size_pt * 0.55


def estimate_line_count(text: str, width_pt: float, font_size_pt: float) -> int:
    if not text:
        return 0
    width_pt = max(width_pt, font_size_pt)
    line_count = 0
    for paragraph in text.split("\n"):
        line_count += 1
        current_width = 0.0
        for character in paragraph:
            width = char_width_pt(character, font_size_pt)
            if current_width and current_width + width > width_pt:
                line_count += 1
                current_width = width
            else:
                current_width += width
    return line_count


def text_metrics(node: ET.Element, bounds: Bounds, text: str) -> tuple[float, float, float]:
    font_size_pt = extract_font_size(node)
    left, right, top, bottom = extract_margins(node)
    available_width_pt = max(
        0.0,
        (bounds.cx - left - right) / EMU_PER_INCH * POINTS_PER_INCH,
    )
    available_height_pt = max(
        0.0,
        (bounds.cy - top - bottom) / EMU_PER_INCH * POINTS_PER_INCH,
    )
    line_count = estimate_line_count(text, available_width_pt, font_size_pt)
    line_height_pt = max(12.0, font_size_pt * 1.2)
    return font_size_pt, line_count * line_height_pt, available_height_pt


def iter_shape_nodes(root: ET.Element) -> Iterable[ET.Element]:
    shape_kinds = {"sp", "pic", "graphicFrame", "cxnSp"}
    return (element for element in root.iter() if local_name(element) in shape_kinds)


def parse_shapes(root: ET.Element, slide_number: int) -> list[Shape]:
    shapes: list[Shape] = []
    for index, node in enumerate(iter_shape_nodes(root), start=1):
        bounds = parse_bounds(node)
        if bounds is None:
            continue
        text = extract_text(node)
        font_size_pt: float | None = None
        required_height_pt: float | None = None
        available_height_pt: float | None = None
        if text.strip():
            font_size_pt, required_height_pt, available_height_pt = text_metrics(
                node, bounds, text
            )
        shapes.append(
            Shape(
                slide=slide_number,
                name=extract_name(node, f"object-{index}"),
                kind=local_name(node),
                bounds=bounds,
                text=text,
                font_size_pt=font_size_pt,
                required_height_pt=required_height_pt,
                available_height_pt=available_height_pt,
            )
        )
    return shapes


def read_slide_size(archive: zipfile.ZipFile) -> Bounds:
    root = ET.fromstring(archive.read("ppt/presentation.xml"))
    size = first_descendant(root, "sldSz")
    if size is None:
        return Bounds(0, 0, int(10 * EMU_PER_INCH), int(5.625 * EMU_PER_INCH))
    return Bounds(0, 0, parse_int(size.get("cx")), parse_int(size.get("cy")))


def slide_number(path: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", path)
    return int(match.group(1)) if match else math.inf


def load_slides(path: Path) -> tuple[Bounds, list[tuple[int, list[Shape]]]]:
    with zipfile.ZipFile(path) as archive:
        slide_size = read_slide_size(archive)
        slide_paths = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=slide_number,
        )
        slides: list[tuple[int, list[Shape]]] = []
        for path_name in slide_paths:
            number = slide_number(path_name)
            root = ET.fromstring(archive.read(path_name))
            slides.append((number, parse_shapes(root, number)))
    return slide_size, slides


def shape_label(shape: Shape) -> str:
    return f"{shape.name} ({shape.kind})"


def add_diagnostic(
    diagnostics: list[Diagnostic],
    slide: int,
    severity: str,
    code: str,
    message: str,
    shape: Shape | None = None,
    related_shape: Shape | None = None,
) -> None:
    diagnostics.append(
        Diagnostic(
            slide=slide,
            severity=severity,
            code=code,
            message=message,
            shape=shape_label(shape) if shape is not None else None,
            related_shape=shape_label(related_shape) if related_shape is not None else None,
        )
    )


def has_page_badge(shapes: Iterable[Shape], slide_size: Bounds) -> bool:
    minimum_x = slide_size.right - int(1.2 * EMU_PER_INCH)
    minimum_y = slide_size.bottom - int(1.0 * EMU_PER_INCH)
    return any(
        shape.is_text
        and re.fullmatch(r"\s*\d{1,3}\s*", shape.text)
        and shape.bounds.x >= minimum_x
        and shape.bounds.y >= minimum_y
        for shape in shapes
    )


def lint_slide(
    slide_number: int,
    shapes: list[Shape],
    slide_size: Bounds,
    require_page_badge: bool,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    boundary_tolerance = int(0.01 * EMU_PER_INCH)

    for shape in shapes:
        bounds = shape.bounds
        if shape.kind == "cxnSp":
            continue
        if (
            bounds.x < -boundary_tolerance
            or bounds.y < -boundary_tolerance
            or bounds.right > slide_size.right + boundary_tolerance
            or bounds.bottom > slide_size.bottom + boundary_tolerance
        ):
            add_diagnostic(
                diagnostics,
                slide_number,
                "error",
                "OUT_OF_BOUNDS",
                "Object extends beyond the slide boundary.",
                shape,
            )
        if shape.is_text and shape.required_height_pt is not None and shape.available_height_pt is not None:
            if shape.required_height_pt > shape.available_height_pt + 1.0:
                add_diagnostic(
                    diagnostics,
                    slide_number,
                    "error",
                    "TEXT_OVERFLOW_ESTIMATE",
                    (
                        f"Estimated text height {shape.required_height_pt:.1f}pt exceeds "
                        f"available box height {shape.available_height_pt:.1f}pt."
                    ),
                    shape,
                )
            if shape.font_size_pt is not None and shape.font_size_pt < 10:
                add_diagnostic(
                    diagnostics,
                    slide_number,
                    "warning",
                    "SMALL_TEXT",
                    f"Text uses an estimated {shape.font_size_pt:.1f}pt font.",
                    shape,
                )

    text_shapes = [shape for shape in shapes if shape.is_text]
    for index, shape in enumerate(text_shapes):
        for other in text_shapes[index + 1 :]:
            if shape.bounds.intersection_area(other.bounds) > int(0.01 * EMU_PER_INCH) ** 2:
                add_diagnostic(
                    diagnostics,
                    slide_number,
                    "error",
                    "TEXT_BOX_OVERLAP",
                    "Two text boxes intersect; inspect the rendered slide and layout coordinates.",
                    shape,
                    other,
                )

    for shape in text_shapes:
        for other in shapes:
            if other is shape or other.is_text or other.kind == "cxnSp":
                continue
            intersection = shape.bounds.intersection_area(other.bounds)
            if intersection == 0:
                continue
            if other.bounds.contains(shape.bounds) or shape.bounds.contains(other.bounds):
                continue
            add_diagnostic(
                diagnostics,
                slide_number,
                "warning",
                "TEXT_OBJECT_OVERLAP",
                "A text box partially intersects a non-text object; confirm this is intentional in the rendered slide.",
                shape,
                other,
            )

    if require_page_badge and slide_number > 1 and not has_page_badge(shapes, slide_size):
        add_diagnostic(
            diagnostics,
            slide_number,
            "error",
            "MISSING_PAGE_BADGE",
            "No numeric page badge was found in the bottom-right safe area.",
        )
    return diagnostics


def build_report(path: Path, require_page_badges: bool) -> dict[str, object]:
    slide_size, slides = load_slides(path)
    all_diagnostics: list[Diagnostic] = []
    slide_reports: list[dict[str, object]] = []
    for number, shapes in slides:
        diagnostics = lint_slide(number, shapes, slide_size, require_page_badges)
        all_diagnostics.extend(diagnostics)
        slide_reports.append(
            {
                "slide": number,
                "objects": len(shapes),
                "status": "FAIL" if any(item.severity == "error" for item in diagnostics) else "PASS",
                "diagnostics": [item.to_dict() for item in diagnostics],
            }
        )

    errors = sum(item.severity == "error" for item in all_diagnostics)
    warnings = sum(item.severity == "warning" for item in all_diagnostics)
    return {
        "artifact": str(path),
        "format": "pptx",
        "slide_size_emu": {"width": slide_size.cx, "height": slide_size.cy},
        "slides": slide_reports,
        "layout": "FAIL" if errors else "PASS",
        "summary": {"errors": errors, "warnings": warnings, "slides": len(slides)},
        "deliverable": errors == 0,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path, help="PPTX file to inspect")
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        help="Also write the machine-readable report to this path",
    )
    parser.add_argument(
        "--require-page-badges",
        action="store_true",
        help="Fail when non-cover slides do not contain a numeric bottom-right page badge",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv or sys.argv[1:])
    if not args.pptx.is_file():
        print(f"error: PPTX file not found: {args.pptx}", file=sys.stderr)
        return 2
    try:
        report = build_report(args.pptx, args.require_page_badges)
    except (OSError, ET.ParseError, KeyError, zipfile.BadZipFile) as error:
        print(f"error: unable to inspect {args.pptx}: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered + "\n", encoding="utf-8")
    return 1 if not report["deliverable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
