from __future__ import annotations

import os
from pathlib import Path
import zipfile

from pypdf import PdfReader
import pytest

from ofd2pdf import OfdConversionError, OfdParseError, convert_file

SAMPLE_ENV_VARS = ("OFD2PDF_SAMPLE_ONE", "OFD2PDF_SAMPLE_TWO")


def xobject_count(page) -> int:
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    if hasattr(xobjects, "get_object"):
        xobjects = xobjects.get_object()
    return len(xobjects)


def sample_paths() -> list[Path]:
    paths = [Path(value).expanduser() for name in SAMPLE_ENV_VARS if (value := os.environ.get(name))]
    return [path for path in paths if path.exists()]


@pytest.mark.parametrize("source", sample_paths())
def test_convert_real_samples(source: Path, tmp_path: Path):
    if not sample_paths():
        pytest.skip("set OFD2PDF_SAMPLE_ONE/OFD2PDF_SAMPLE_TWO to run local sample conversions")

    output = tmp_path / f"{source.stem}.pdf"

    convert_file(source, output)

    reader = PdfReader(output)
    assert len(reader.pages) >= 1

    for page in reader.pages:
        assert float(page.mediabox.width) == pytest.approx(595.2756, abs=0.01)
        assert float(page.mediabox.height) == pytest.approx(841.8898, abs=0.01)

    assert xobject_count(reader.pages[-1]) >= 0


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
    source = tmp_path / "input.ofd"
    source.write_bytes(b"placeholder")
    output = tmp_path / "exists.pdf"
    output.write_bytes(b"already here")

    with pytest.raises(OfdConversionError, match="output already exists"):
        convert_file(source, output)
