# ofd2pdf

`ofd2pdf` converts OFD fixed-layout documents into real PDF files by parsing
the OFD ZIP/XML package and rendering pages with embedded resources.

It is not a print-wrapper and does not require an OFD viewer.

## Features

- Parses OFD ZIP/XML packages directly.
- Renders pages to PDF with ReportLab.
- Supports embedded TrueType fonts, positioned text, basic paths, colors,
  alpha, image resources, stamp annotations, and Pattern-based diagonal
  watermarks used by common Chinese document workflows.
- Fails with a clear diagnostic error when required OFD content is not
  supported yet.

## Installation

With `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

With `pip`:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Usage

```bash
ofd2pdf input.ofd -o output.pdf
ofd2pdf *.ofd --out-dir output/pdf --overwrite
ofd2pdf ./documents --recursive --out-dir output/pdf
```

You can also run the module directly:

```bash
python -m ofd2pdf input.ofd -o output.pdf
```

## Development

```bash
pytest -q
```

The repository ignores local `.ofd` files and generated PDFs by default because
real OFD documents commonly contain private data. Tests that require the local
sample OFD files are skipped automatically when those files are not present.

## Publishing Notes

Before pushing to a public GitHub repository, make sure you do not commit real
business documents, generated PDFs, virtual environments, or local caches.

No license file is included yet. Add one explicitly before publishing if you
want others to have clear permission to use or modify the project.
