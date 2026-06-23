from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import posixpath
import zipfile

from defusedxml import ElementTree as SafeET

from .exceptions import OfdParseError

NS = "{http://www.ofdspec.org/2016}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def child(element, name: str):
    for item in element:
        if local_name(item.tag) == name:
            return item
    return None


def children(element, name: str):
    return [item for item in element if local_name(item.tag) == name]


def descendants(element, name: str):
    for item in element.iter():
        if local_name(item.tag) == name:
            yield item


def text_of(element, name: str) -> str | None:
    item = child(element, name)
    if item is None or item.text is None:
        return None
    return item.text.strip()


def parse_xml(data: bytes, source: str):
    try:
        return SafeET.fromstring(data)
    except Exception as exc:  # defusedxml wraps several parser errors
        raise OfdParseError(f"invalid XML in {source}: {exc}") from exc


def normalize_zip_path(path: str | PurePosixPath) -> str:
    normalized = posixpath.normpath(str(path).replace("\\", "/"))
    if normalized.startswith("../") or normalized == "..":
        raise OfdParseError(f"unsafe relative path in OFD: {path}")
    return normalized.lstrip("/")


def join_zip_path(base_dir: str, relative: str) -> str:
    return normalize_zip_path(PurePosixPath(base_dir) / relative)


def parse_floats(value: str | None, expected: int | None = None) -> list[float]:
    if value is None:
        if expected is None:
            return []
        raise OfdParseError("missing numeric value")
    try:
        values = [float(part) for part in value.replace(",", " ").split()]
    except ValueError as exc:
        raise OfdParseError(f"invalid numeric value: {value}") from exc
    if expected is not None and len(values) != expected:
        raise OfdParseError(f"expected {expected} numbers, got {len(values)}: {value}")
    return values


@dataclass(frozen=True)
class FontResource:
    id: str
    name: str
    zip_path: str | None


@dataclass(frozen=True)
class ImageResource:
    id: str
    zip_path: str
    media_type: str | None = None
    format: str | None = None


@dataclass(frozen=True)
class PageInfo:
    id: str
    zip_path: str
    area_mm: tuple[float, float, float, float]
    annotation_zip_path: str | None = None


@dataclass
class OfdDocument:
    source_path: Path
    zip_file: zipfile.ZipFile
    doc_root: str
    doc_dir: str
    document_xml: object
    pages: list[PageInfo]
    fonts: dict[str, FontResource] = field(default_factory=dict)
    images: dict[str, ImageResource] = field(default_factory=dict)

    def read(self, zip_path: str) -> bytes:
        try:
            return self.zip_file.read(zip_path)
        except KeyError as exc:
            raise OfdParseError(f"missing file in OFD package: {zip_path}") from exc

    def xml(self, zip_path: str):
        return parse_xml(self.read(zip_path), zip_path)

    def close(self) -> None:
        self.zip_file.close()

    def __enter__(self) -> "OfdDocument":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def open_ofd(path: Path) -> OfdDocument:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise OfdParseError(f"not a valid OFD ZIP package: {path}") from exc

    try:
        ofd_xml = parse_xml(zf.read("OFD.xml"), "OFD.xml")
    except KeyError as exc:
        zf.close()
        raise OfdParseError("missing OFD.xml") from exc

    doc_root_text = None
    for item in descendants(ofd_xml, "DocRoot"):
        if item.text:
            doc_root_text = item.text.strip()
            break
    if not doc_root_text:
        zf.close()
        raise OfdParseError("OFD.xml does not contain a DocRoot")

    doc_root = normalize_zip_path(doc_root_text)
    doc_dir = posixpath.dirname(doc_root)
    try:
        document_xml = parse_xml(zf.read(doc_root), doc_root)
    except KeyError as exc:
        zf.close()
        raise OfdParseError(f"missing document root: {doc_root}") from exc

    area = read_default_page_area(document_xml)
    fonts: dict[str, FontResource] = {}
    images: dict[str, ImageResource] = {}
    for res_path in resource_paths(document_xml, doc_dir):
        read_resources(zf, res_path, fonts, images)

    annotation_map = read_annotation_map(zf, document_xml, doc_dir)
    pages = read_pages(document_xml, doc_dir, area, annotation_map)
    if not pages:
        zf.close()
        raise OfdParseError("document contains no pages")

    return OfdDocument(
        source_path=path,
        zip_file=zf,
        doc_root=doc_root,
        doc_dir=doc_dir,
        document_xml=document_xml,
        pages=pages,
        fonts=fonts,
        images=images,
    )


def read_default_page_area(document_xml) -> tuple[float, float, float, float]:
    common = child(document_xml, "CommonData")
    if common is None:
        raise OfdParseError("Document.xml missing CommonData")
    page_area = child(common, "PageArea")
    if page_area is None:
        raise OfdParseError("Document.xml missing PageArea")
    physical = text_of(page_area, "PhysicalBox")
    values = parse_floats(physical, expected=4)
    return values[0], values[1], values[2], values[3]


def resource_paths(document_xml, doc_dir: str) -> list[str]:
    common = child(document_xml, "CommonData")
    if common is None:
        return []
    paths: list[str] = []
    for name in ("PublicRes", "DocumentRes"):
        for item in children(common, name):
            if item.text:
                paths.append(join_zip_path(doc_dir, item.text.strip()))
    return paths


def read_resources(
    zf: zipfile.ZipFile,
    res_path: str,
    fonts: dict[str, FontResource],
    images: dict[str, ImageResource],
) -> None:
    try:
        root = parse_xml(zf.read(res_path), res_path)
    except KeyError as exc:
        raise OfdParseError(f"missing resource file: {res_path}") from exc

    res_dir = posixpath.dirname(res_path)
    base_loc = root.attrib.get("BaseLoc", "")
    base_dir = join_zip_path(res_dir, base_loc) if base_loc else res_dir

    for font in descendants(root, "Font"):
        font_id = font.attrib.get("ID")
        if not font_id:
            continue
        font_name = font.attrib.get("FontName") or font.attrib.get("FamilyName") or f"Font{font_id}"
        font_file = text_of(font, "FontFile")
        zip_path = join_zip_path(base_dir, font_file) if font_file else None
        fonts[font_id] = FontResource(font_id, font_name, zip_path)

    for media in descendants(root, "MultiMedia"):
        media_id = media.attrib.get("ID")
        media_file = text_of(media, "MediaFile")
        if not media_id or not media_file:
            continue
        images[media_id] = ImageResource(
            id=media_id,
            zip_path=join_zip_path(base_dir, media_file),
            media_type=media.attrib.get("Type"),
            format=media.attrib.get("Format"),
        )


def read_pages(
    document_xml,
    doc_dir: str,
    default_area: tuple[float, float, float, float],
    annotation_map: dict[str, str],
) -> list[PageInfo]:
    pages_node = child(document_xml, "Pages")
    if pages_node is None:
        raise OfdParseError("Document.xml missing Pages")

    pages: list[PageInfo] = []
    for page in children(pages_node, "Page"):
        page_id = page.attrib.get("ID")
        base_loc = page.attrib.get("BaseLoc")
        if not page_id or not base_loc:
            raise OfdParseError("Page entry missing ID or BaseLoc")
        pages.append(
            PageInfo(
                id=page_id,
                zip_path=join_zip_path(doc_dir, base_loc),
                area_mm=default_area,
                annotation_zip_path=annotation_map.get(page_id),
            )
        )
    return pages


def read_annotation_map(
    zf: zipfile.ZipFile,
    document_xml,
    doc_dir: str,
) -> dict[str, str]:
    annotations = text_of(document_xml, "Annotations")
    if not annotations:
        return {}
    annotation_root_path = join_zip_path(doc_dir, annotations)
    try:
        root = parse_xml(zf.read(annotation_root_path), annotation_root_path)
    except KeyError:
        return {}

    annotation_dir = posixpath.dirname(annotation_root_path)
    result: dict[str, str] = {}
    for page in children(root, "Page"):
        page_id = page.attrib.get("PageID")
        file_loc = text_of(page, "FileLoc")
        if page_id and file_loc:
            result[page_id] = join_zip_path(annotation_dir, file_loc)
    return result
