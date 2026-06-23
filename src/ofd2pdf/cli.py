from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .converter import convert_file
from .exceptions import OfdConversionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofd2pdf",
        description="Convert OFD fixed-layout documents to PDF.",
    )
    parser.add_argument("inputs", nargs="+", help="OFD files or directories to convert")
    parser.add_argument("-o", "--output", help="Output PDF path for a single input file")
    parser.add_argument("--out-dir", help="Directory for converted PDFs")
    parser.add_argument("--recursive", action="store_true", help="Search directories recursively")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PDF files")
    parser.add_argument(
        "--font-dir",
        action="append",
        default=[],
        help="Additional directory to search for fonts when an OFD font is not embedded",
    )
    parser.add_argument("--verbose", action="store_true", help="Print each converted output path")
    return parser


def iter_inputs(paths: list[str], recursive: bool) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*.ofd" if recursive else "*.ofd"
            found.extend(sorted(path.glob(pattern)))
        else:
            found.append(path)
    return found


def output_for(input_path: Path, output: str | None, out_dir: str | None, total: int) -> Path:
    if output:
        if total != 1:
            raise OfdConversionError("--output can only be used with one input file")
        return Path(output)
    if out_dir:
        return Path(out_dir) / f"{input_path.stem}.pdf"
    return input_path.with_suffix(".pdf")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        inputs = iter_inputs(args.inputs, args.recursive)
        if not inputs:
            raise OfdConversionError("no input files found")
        for path in inputs:
            if not path.exists():
                raise OfdConversionError(f"input does not exist: {path}")
            if path.is_dir():
                continue
            if path.suffix.lower() != ".ofd":
                raise OfdConversionError(f"input is not an .ofd file: {path}")

        for input_path in inputs:
            if input_path.is_dir():
                continue
            output_path = output_for(input_path, args.output, args.out_dir, len(inputs))
            convert_file(
                input_path,
                output_path,
                overwrite=args.overwrite,
                font_dirs=[Path(p) for p in args.font_dir],
            )
            if args.verbose:
                print(output_path)
    except OfdConversionError as exc:
        print(f"ofd2pdf: {exc}", file=sys.stderr)
        return 2

    return 0
