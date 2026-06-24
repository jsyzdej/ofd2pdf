from __future__ import annotations

from pathlib import Path
import tempfile

from .exceptions import OfdConversionError
from .ofd import open_ofd
from .renderer import PdfRenderer


def convert_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    overwrite: bool = False,
    font_dirs: list[Path] | None = None,
) -> Path:
    source = Path(input_path)
    target = Path(output_path) if output_path is not None else source.with_suffix(".pdf")

    if not source.exists():
        raise OfdConversionError(f"input does not exist: {source}")
    if source.suffix.lower() != ".ofd":
        raise OfdConversionError(f"input is not an .ofd file: {source}")
    if target.exists() and not overwrite:
        raise OfdConversionError(f"output already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".tmp.pdf",
            dir=target.parent,
            delete=False,
        ) as temp:
            temp_name = Path(temp.name)

        with open_ofd(source) as document:
            renderer = PdfRenderer(document, temp_name, font_dirs=font_dirs or [])
            renderer.render()

        temp_name.replace(target)
        return target
    except Exception:
        if temp_name is not None and temp_name.exists():
            temp_name.unlink()
        raise
