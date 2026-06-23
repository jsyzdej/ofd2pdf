from __future__ import annotations

from pathlib import Path
import zipfile

from pypdf import PdfReader
import pytest

from ofd2pdf import OfdConversionError, OfdParseError, convert_file

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ONE = ROOT / "关于在日班工作模式执行夏令作息时间的通知(复制件).ofd"
SAMPLE_TWO = ROOT / "关于开展2026年度上海石化青年人才创新创效竞赛的通知(复制件).ofd"
HAS_SAMPLE_FIXTURES = SAMPLE_ONE.exists() and SAMPLE_TWO.exists()


def compact_text(reader: PdfReader) -> str:
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return "".join(text.split())


def xobject_count(page) -> int:
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    if hasattr(xobjects, "get_object"):
        xobjects = xobjects.get_object()
    return len(xobjects)


@pytest.mark.parametrize(
    ("source", "page_count", "expected_snippets", "expected_xobjects"),
    [
        (SAMPLE_ONE, 1, ("关于在日班工作模式执行夏令作息时间的通知",), 1),
        (SAMPLE_TWO, 4, ("内部上海石化", "2026"), 3),
    ],
)
@pytest.mark.skipif(not HAS_SAMPLE_FIXTURES, reason="local OFD sample fixtures are not committed")
def test_convert_real_samples(
    source: Path,
    page_count: int,
    expected_snippets: tuple[str, ...],
    expected_xobjects: int,
    tmp_path: Path,
):
    output = tmp_path / f"{source.stem}.pdf"

    convert_file(source, output)

    reader = PdfReader(output)
    assert len(reader.pages) == page_count
    text = compact_text(reader)
    for snippet in expected_snippets:
        assert snippet in text

    for page in reader.pages:
        assert float(page.mediabox.width) == pytest.approx(595.2756, abs=0.01)
        assert float(page.mediabox.height) == pytest.approx(841.8898, abs=0.01)

    assert xobject_count(reader.pages[-1]) == expected_xobjects


def test_rejects_invalid_zip(tmp_path: Path):
    bad = tmp_path / "bad.ofd"
    bad.write_bytes(b"not a zip")

    with pytest.raises(OfdParseError, match="not a valid OFD ZIP package"):
        convert_file(bad, tmp_path / "bad.pdf")


def test_rejects_missing_ofd_xml(tmp_path: Path):
    bad = tmp_path / "missing.ofd"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("Doc_0/Document.xml", "<Document/>")

    with pytest.raises(OfdParseError, match="missing OFD.xml"):
        convert_file(bad, tmp_path / "missing.pdf")


def test_refuses_to_overwrite_existing_output(tmp_path: Path):
    if not SAMPLE_ONE.exists():
        pytest.skip("local OFD sample fixture is not committed")

    output = tmp_path / "exists.pdf"
    output.write_bytes(b"already here")

    with pytest.raises(OfdConversionError, match="output already exists"):
        convert_file(SAMPLE_ONE, output)
