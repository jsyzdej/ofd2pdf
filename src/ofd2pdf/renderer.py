from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from io import BytesIO
import math
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from PIL import Image
from reportlab.lib.colors import Color, black
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .exceptions import OfdParseError, OfdUnsupportedError
from .ofd import (
    ImageResource,
    OfdDocument,
    PageInfo,
    child,
    children,
    descendants,
    local_name,
    parse_floats,
)

MM_TO_PT = 72.0 / 25.4
NUMBER_OR_COMMAND = re.compile(r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class Matrix:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.a * x + self.c * y + self.e,
            self.b * x + self.d * y + self.f,
        )

    def inverse(self) -> "Matrix":
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-9:
            raise OfdUnsupportedError("pattern CTM is not invertible")
        return Matrix(
            self.d / det,
            -self.b / det,
            -self.c / det,
            self.a / det,
            (self.c * self.f - self.d * self.e) / det,
            (self.b * self.e - self.a * self.f) / det,
        )

    @property
    def pdf_angle_degrees(self) -> float:
        return math.degrees(math.atan2(-self.b, self.a))

    @property
    def x_scale(self) -> float:
        return math.hypot(self.a, self.b)


def mm(value: float) -> float:
    return value * MM_TO_PT


def pt_to_mm(value: float) -> float:
    return value / MM_TO_PT


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes"}


class PdfRenderer:
    def __init__(self, document: OfdDocument, output_path: Path, font_dirs: list[Path]) -> None:
        self.document = document
        self.output_path = output_path
        self.font_dirs = font_dirs
        self.canvas: canvas.Canvas | None = None
        self.page: PageInfo | None = None
        self.page_width_pt = 0.0
        self.page_height_pt = 0.0
        self._temp_path: Path | None = None
        self._run_id = uuid4().hex[:8]
        self._font_ids: dict[str, str] = {}
        self._font_names: dict[str, str] = {}

    def render(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self._temp_path = Path(temp_dir)
            self._register_embedded_fonts()

            first = self.document.pages[0]
            _, _, width_mm, height_mm = first.area_mm
            pdf = canvas.Canvas(str(self.output_path), pagesize=(mm(width_mm), mm(height_mm)))
            self.canvas = pdf
            pdf.setTitle(self.document.source_path.stem)

            for index, page in enumerate(self.document.pages):
                if index:
                    _, _, width_mm, height_mm = page.area_mm
                    pdf.setPageSize((mm(width_mm), mm(height_mm)))
                self._render_page(page)
                pdf.showPage()

            pdf.save()

    def _register_embedded_fonts(self) -> None:
        if self._temp_path is None:
            raise RuntimeError("temporary font directory has not been initialized")
        for font_id, resource in self.document.fonts.items():
            if not resource.zip_path:
                continue
            font_file = self._temp_path / f"{self._run_id}_font_{font_id}_{Path(resource.zip_path).name}"
            font_file.write_bytes(self.document.read(resource.zip_path))
            font_name = self._pdf_font_name(font_id, resource.zip_path)
            try:
                font = TTFont(font_name, str(font_file))
                font.face.name = font_name.encode("ascii")
                pdfmetrics.registerFont(font)
            except Exception as exc:
                raise OfdUnsupportedError(
                    f"cannot register embedded font {resource.name} ({resource.zip_path}): {exc}"
                ) from exc
            self._font_ids[font_id] = font_name
            self._font_names.setdefault(resource.name, font_name)

        for font_id, resource in self.document.fonts.items():
            if font_id in self._font_ids:
                continue
            if resource.name in self._font_names:
                self._font_ids[font_id] = self._font_names[resource.name]
                continue
            found = self._find_external_font(resource.name)
            if found:
                font_name = self._pdf_font_name(font_id, str(found))
                try:
                    font = TTFont(font_name, str(found))
                    font.face.name = font_name.encode("ascii")
                    pdfmetrics.registerFont(font)
                except Exception as exc:
                    raise OfdUnsupportedError(f"cannot register font {found}: {exc}") from exc
                self._font_ids[font_id] = font_name
                self._font_names.setdefault(resource.name, font_name)

    def _pdf_font_name(self, font_id: str, source: str) -> str:
        digest = sha1(f"{self._run_id}:{self.document.source_path}:{font_id}:{source}".encode("utf-8")).hexdigest()[:12]
        return f"ofd_{font_id}_{digest}"

    def _find_external_font(self, font_name: str) -> Path | None:
        search_dirs = [
            *self.font_dirs,
            Path.home() / "Library/Fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path("/opt/homebrew/share/fonts"),
        ]
        normalized = font_name.lower().replace(" ", "")
        for directory in search_dirs:
            if not directory.exists():
                continue
            for candidate in directory.rglob("*"):
                if candidate.suffix.lower() not in {".ttf", ".otf"}:
                    continue
                stem = candidate.stem.lower().replace(" ", "")
                if normalized and normalized in stem:
                    return candidate
        return None

    def _font_for(self, font_id: str | None) -> str:
        if not font_id:
            raise OfdUnsupportedError("TextObject missing Font attribute")
        if font_id in self._font_ids:
            return self._font_ids[font_id]
        resource = self.document.fonts.get(font_id)
        if resource is None:
            raise OfdUnsupportedError(f"font resource not found: {font_id}")
        raise OfdUnsupportedError(f"font resource has no usable font file: {resource.name} ({font_id})")

    def _render_page(self, page: PageInfo) -> None:
        self.page = page
        _, _, width_mm, height_mm = page.area_mm
        self.page_width_pt = mm(width_mm)
        self.page_height_pt = mm(height_mm)

        page_xml = self.document.xml(page.zip_path)
        content = child(page_xml, "Content")
        if content is not None:
            self._render_container(content, origin=(0.0, 0.0))

        if page.annotation_zip_path:
            annot_xml = self.document.xml(page.annotation_zip_path)
            self._render_annotations(annot_xml)

    def _render_container(self, element, origin: tuple[float, float]) -> None:
        for item in element:
            name = local_name(item.tag)
            if name in {"Layer", "Content", "PageBlock", "Appearance"}:
                self._render_container(item, origin)
            elif name == "TextObject":
                self._render_text(item, origin)
            elif name == "PathObject":
                self._render_path(item, origin)
            elif name == "ImageObject":
                self._render_image(item, origin)
            elif name in {"FillColor", "StrokeColor", "Pattern", "CellContent"}:
                continue
            elif name.endswith("Object"):
                raise OfdUnsupportedError(f"unsupported OFD object: {name}")

    def _render_annotations(self, annot_xml) -> None:
        for annot in descendants(annot_xml, "Annot"):
            appearance = child(annot, "Appearance")
            if appearance is None:
                continue
            bx, by, _, _ = self._boundary(appearance)
            self._render_container(appearance, origin=(bx, by))

    def _render_text(self, element, origin: tuple[float, float]) -> None:
        pdf = self._pdf
        bx, by, _, _ = self._boundary(element)
        font_name = self._font_for(element.attrib.get("Font"))
        font_size = mm(float(element.attrib.get("Size", "3.5")))
        fill = parse_bool(element.attrib.get("Fill"), True)
        stroke = parse_bool(element.attrib.get("Stroke"), False)
        if not fill and not stroke:
            return

        fill_color = self._color(child(element, "FillColor"), black)
        stroke_color = self._color(child(element, "StrokeColor"), fill_color)
        alpha = self._alpha(element.attrib.get("Alpha"))
        line_width = mm(float(element.attrib.get("LineWidth", "0.1")))
        mode = 2 if fill and stroke else 1 if stroke else 0

        pdf.saveState()
        pdf.setFont(font_name, font_size)
        pdf.setFillColor(fill_color)
        pdf.setStrokeColor(stroke_color)
        pdf.setLineWidth(line_width)
        pdf.setFillAlpha(alpha)
        pdf.setStrokeAlpha(alpha)

        for code in children(element, "TextCode"):
            text = code.text or ""
            if not text:
                continue
            x0 = origin[0] + bx + float(code.attrib.get("X", "0"))
            y0 = origin[1] + by + float(code.attrib.get("Y", "0"))
            deltas_x = parse_floats(code.attrib.get("DeltaX")) if code.attrib.get("DeltaX") else []
            deltas_y = parse_floats(code.attrib.get("DeltaY")) if code.attrib.get("DeltaY") else []
            if not deltas_x and not deltas_y:
                self._draw_text_piece(text, x0, y0, font_name, font_size, mode)
                continue

            cursor_x = x0
            cursor_y = y0
            for index, char in enumerate(text):
                self._draw_text_piece(char, cursor_x, cursor_y, font_name, font_size, mode)
                if index < len(deltas_x):
                    cursor_x += deltas_x[index]
                else:
                    cursor_x += pt_to_mm(pdfmetrics.stringWidth(char, font_name, font_size))
                if index < len(deltas_y):
                    cursor_y += deltas_y[index]

        pdf.restoreState()

    def _draw_text_piece(self, text: str, x_mm: float, y_mm: float, font_name: str, font_size: float, mode: int) -> None:
        x, y = self._point(x_mm, y_mm)
        if mode == 0:
            self._pdf.drawString(x, y, text)
            return
        item = self._pdf.beginText()
        item.setTextOrigin(x, y)
        item.setFont(font_name, font_size)
        item.setTextRenderMode(mode)
        item.textOut(text)
        self._pdf.drawText(item)

    def _render_text_transformed(
        self,
        element,
        matrix: Matrix,
        tile: tuple[float, float],
        origin: tuple[float, float],
    ) -> None:
        pdf = self._pdf
        bx, by, _, _ = self._boundary(element)
        font_name = self._font_for(element.attrib.get("Font"))
        font_size = mm(float(element.attrib.get("Size", "3.5")) * matrix.x_scale)
        fill_color = self._color(child(element, "FillColor"), black)
        alpha = self._alpha(element.attrib.get("Alpha"))
        angle = matrix.pdf_angle_degrees

        pdf.saveState()
        pdf.setFont(font_name, font_size)
        pdf.setFillColor(fill_color)
        pdf.setFillAlpha(alpha)
        for code in children(element, "TextCode"):
            text = code.text or ""
            if not text:
                continue
            x0 = tile[0] + bx + float(code.attrib.get("X", "0"))
            y0 = tile[1] + by + float(code.attrib.get("Y", "0"))
            deltas_x = parse_floats(code.attrib.get("DeltaX")) if code.attrib.get("DeltaX") else []
            cursor_x = x0
            for index, char in enumerate(text):
                tx, ty = matrix.apply(cursor_x, y0)
                tx += origin[0]
                ty += origin[1]
                x, y = self._point(tx, ty)
                pdf.saveState()
                pdf.translate(x, y)
                pdf.rotate(angle)
                pdf.drawString(0, 0, char)
                pdf.restoreState()
                if index < len(deltas_x):
                    cursor_x += deltas_x[index]
                else:
                    cursor_x += pt_to_mm(pdfmetrics.stringWidth(char, font_name, font_size))
        pdf.restoreState()

    def _render_path(self, element, origin: tuple[float, float]) -> None:
        fill_color_node = child(element, "FillColor")
        pattern = child(fill_color_node, "Pattern") if fill_color_node is not None else None
        if pattern is not None:
            self._render_pattern(pattern, element, origin)
            return

        pdf = self._pdf
        path = pdf.beginPath()
        bx, by, _, _ = self._boundary(element)
        current: tuple[float, float] | None = None
        data = child(element, "AbbreviatedData")
        if data is None or not (data.text or "").strip():
            raise OfdUnsupportedError("PathObject missing AbbreviatedData")

        def convert(px: float, py: float) -> tuple[float, float]:
            return self._point(origin[0] + bx + px, origin[1] + by + py)

        tokens = NUMBER_OR_COMMAND.findall(data.text or "")
        index = 0
        command = ""
        while index < len(tokens):
            if tokens[index].isalpha():
                command = tokens[index].upper()
                index += 1
            if command in {"Z", "C"} and (index >= len(tokens) or tokens[index].isalpha()):
                path.close()
                current = None
                continue
            if command in {"M", "L"}:
                while index + 1 < len(tokens) and not tokens[index].isalpha():
                    px = float(tokens[index])
                    py = float(tokens[index + 1])
                    x, y = convert(px, py)
                    if command == "M":
                        path.moveTo(x, y)
                        command = "L"
                    else:
                        path.lineTo(x, y)
                    current = (x, y)
                    index += 2
                continue
            if command in {"B", "C"}:
                if index + 5 >= len(tokens):
                    raise OfdParseError("cubic path command missing coordinates")
                x1, y1 = convert(float(tokens[index]), float(tokens[index + 1]))
                x2, y2 = convert(float(tokens[index + 2]), float(tokens[index + 3]))
                x3, y3 = convert(float(tokens[index + 4]), float(tokens[index + 5]))
                path.curveTo(x1, y1, x2, y2, x3, y3)
                current = (x3, y3)
                index += 6
                continue
            if command == "Q":
                if current is None or index + 3 >= len(tokens):
                    raise OfdParseError("quadratic path command missing coordinates")
                qx, qy = convert(float(tokens[index]), float(tokens[index + 1]))
                ex, ey = convert(float(tokens[index + 2]), float(tokens[index + 3]))
                cx, cy = current
                c1 = (cx + 2.0 / 3.0 * (qx - cx), cy + 2.0 / 3.0 * (qy - cy))
                c2 = (ex + 2.0 / 3.0 * (qx - ex), ey + 2.0 / 3.0 * (qy - ey))
                path.curveTo(c1[0], c1[1], c2[0], c2[1], ex, ey)
                current = (ex, ey)
                index += 4
                continue
            if command == "A":
                raise OfdUnsupportedError("elliptical arc path command is not supported yet")
            raise OfdUnsupportedError(f"unsupported path command: {command}")

        fill = parse_bool(element.attrib.get("Fill"), False)
        stroke = parse_bool(element.attrib.get("Stroke"), not fill)

        pdf.saveState()
        self._apply_blend_mode(element.attrib.get("BlendMode"))
        pdf.setStrokeColor(self._color(child(element, "StrokeColor"), black))
        pdf.setFillColor(self._color(fill_color_node, black))
        pdf.setLineWidth(mm(float(element.attrib.get("LineWidth", "0.1"))))
        alpha = self._alpha(element.attrib.get("Alpha"))
        pdf.setFillAlpha(alpha)
        pdf.setStrokeAlpha(alpha)
        pdf.drawPath(path, stroke=1 if stroke else 0, fill=1 if fill else 0)
        pdf.restoreState()

    def _render_pattern(self, pattern, path_element, origin: tuple[float, float]) -> None:
        matrix = self._matrix(pattern.attrib.get("CTM"))
        x_step = float(pattern.attrib.get("XStep", pattern.attrib.get("Width", "0")))
        y_step = float(pattern.attrib.get("YStep", pattern.attrib.get("Height", "0")))
        if not x_step or not y_step:
            raise OfdUnsupportedError("Pattern missing XStep/YStep")
        cell = child(pattern, "CellContent")
        if cell is None:
            return

        bx, by, bw, bh = self._boundary(path_element)
        target_corners = [
            (0.0, 0.0),
            (bw, 0.0),
            (0.0, bh),
            (bw, bh),
        ]
        inverse = matrix.inverse()
        pattern_points = [inverse.apply(x, y) for x, y in target_corners]
        min_x = min(x for x, _ in pattern_points)
        max_x = max(x for x, _ in pattern_points)
        min_y = min(y for _, y in pattern_points)
        max_y = max(y for _, y in pattern_points)
        start_i = math.floor(min_x / x_step) - 2
        end_i = math.ceil(max_x / x_step) + 2
        start_j = math.floor(min_y / y_step) - 2
        end_j = math.ceil(max_y / y_step) + 2

        self._pdf.saveState()
        self._apply_blend_mode(path_element.attrib.get("BlendMode"))
        pattern_origin = (origin[0] + bx, origin[1] + by)
        for i in range(start_i, end_i + 1):
            for j in range(start_j, end_j + 1):
                tile = (i * x_step, j * y_step)
                for item in cell:
                    name = local_name(item.tag)
                    if name == "TextObject":
                        self._render_text_transformed(item, matrix, tile, pattern_origin)
                    else:
                        raise OfdUnsupportedError(f"unsupported Pattern CellContent object: {name}")
        self._pdf.restoreState()

    def _render_image(self, element, origin: tuple[float, float]) -> None:
        resource_id = element.attrib.get("ResourceID")
        if not resource_id:
            raise OfdUnsupportedError("ImageObject missing ResourceID")
        resource = self.document.images.get(resource_id)
        if resource is None:
            raise OfdUnsupportedError(f"image resource not found: {resource_id}")
        bx, by, bw, bh = self._boundary(element)
        if bw <= 0 or bh <= 0:
            bw, bh = self._size_from_ctm(element, resource)

        image_data = self.document.read(resource.zip_path)
        reader = ImageReader(BytesIO(image_data))
        x = mm(origin[0] + bx)
        y = self.page_height_pt - mm(origin[1] + by + bh)
        width = mm(bw)
        height = mm(bh)

        self._pdf.saveState()
        self._apply_blend_mode(element.attrib.get("BlendMode"))
        alpha = self._alpha(element.attrib.get("Alpha"))
        self._pdf.setFillAlpha(alpha)
        self._pdf.drawImage(reader, x, y, width=width, height=height, mask="auto")
        self._pdf.restoreState()

    def _size_from_ctm(self, element, resource: ImageResource) -> tuple[float, float]:
        ctm = element.attrib.get("CTM")
        if ctm:
            values = parse_floats(ctm, expected=6)
            width = abs(values[0]) or abs(values[2])
            height = abs(values[3]) or abs(values[1])
            if width and height:
                return width, height
        image = Image.open(BytesIO(self.document.read(resource.zip_path)))
        return float(image.width), float(image.height)

    def _boundary(self, element) -> tuple[float, float, float, float]:
        values = parse_floats(element.attrib.get("Boundary"), expected=4)
        return values[0], values[1], values[2], values[3]

    def _matrix(self, value: str | None) -> Matrix:
        if not value:
            return Matrix(1, 0, 0, 1, 0, 0)
        values = parse_floats(value, expected=6)
        return Matrix(*values)

    def _point(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        return mm(x_mm), self.page_height_pt - mm(y_mm)

    def _color(self, element, default=black):
        if element is None:
            return default
        value = element.attrib.get("Value")
        if not value:
            return default
        parts = parse_floats(value)
        if len(parts) >= 3:
            return Color(parts[0] / 255.0, parts[1] / 255.0, parts[2] / 255.0)
        if len(parts) == 1:
            gray = parts[0] / 255.0
            return Color(gray, gray, gray)
        return default

    def _alpha(self, value: str | None) -> float:
        if value is None:
            return 1.0
        try:
            alpha = float(value)
        except ValueError as exc:
            raise OfdParseError(f"invalid alpha value: {value}") from exc
        return max(0.0, min(1.0, alpha / 255.0 if alpha > 1 else alpha))

    def _apply_blend_mode(self, value: str | None) -> None:
        if not value:
            return
        try:
            self._pdf.setBlendMode(value)
        except Exception:
            pass

    @property
    def _pdf(self) -> canvas.Canvas:
        if self.canvas is None:
            raise RuntimeError("renderer has not been initialized")
        return self.canvas
