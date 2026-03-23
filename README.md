# chrome-ocr

[![Tests](https://github.com/ayismas/chrome-ocr/actions/workflows/test.yml/badge.svg)](https://github.com/ayismas/chrome-ocr/actions/workflows/test.yml)

Turn local PDFs and images into Markdown with Chrome's hidden OCR engine.

No API key. No cloud bill. No model download. Chrome already ships the model; this project calls it directly.

## Why This Is Interesting

- It reuses Chrome's built-in Screen AI component instead of shipping another OCR model.
- It stays local, so you can process documents without sending them to a cloud API.
- It returns layout-aware Markdown, not just a flat text dump.
- It handles the fast path for text-layer PDFs and only OCRs pages that actually need it.

## Quick Demo

This project is source-install first.

```bash
git clone https://github.com/ayismas/chrome-ocr.git
cd chrome-ocr
pip install -e .[pdf]
```

Check whether Chrome's OCR component is available:

```bash
chrome-ocr doctor
python -m chrome_ocr doctor
```

Extract a PDF to Markdown:

```bash
chrome-ocr pdf report.pdf -o report.md
chrome-ocr pdf report.pdf --pages 1,3,5-8 --dpi 300
```

OCR an image:

```bash
chrome-ocr img scan.png
chrome-ocr img scan.png -o scan.md
```

## Python API

```python
from chrome_ocr import ocr_img, ocr_pdf

markdown = ocr_pdf("report.pdf")
markdown = ocr_pdf("report.pdf", pages=[1, 3, 5], dpi=300)

text = ocr_img("scan.png")
```

Low-level engine reuse is also available:

```python
from chrome_ocr import ScreenAIEngine, ocr_pdf

engine = ScreenAIEngine()
markdown = ocr_pdf("report.pdf", engine=engine)
```

## What You Get

- **PDF to Markdown**: direct extraction for text PDFs, OCR fallback for scanned pages.
- **Image to Markdown**: file paths, `PIL.Image`, and NumPy arrays are supported.
- **Layout-aware output**: headings, paragraph breaks, indented blocks, tables, and formulas are reconstructed from geometry.
- **Cheap warm runs**: the DLL is loaded once per process and reused afterwards.

## CLI Reference

### `chrome-ocr doctor`

Reports whether Chrome's `chrome_screen_ai.dll` is present and whether it initializes correctly.

### `chrome-ocr img INPUT [-o OUTPUT]`

OCR an image and print Markdown to stdout, or write it to a file with `-o`.

### `chrome-ocr pdf INPUT [-o OUTPUT] [--dpi 200] [--pages 1,3,5-8]`

Extract or OCR a PDF and emit Markdown.

- `--pages` uses 1-based indexing.
- `--page-sep` controls how multiple pages are joined.
- `--dpi` affects scanned-page rasterization quality.

## API Reference

### `ocr_pdf(pdf_path, *, dpi=200, pages=None, page_sep="\n\n", engine=None) -> str`

Returns only the content extracted from the PDF. It does not inject a file title or page headers.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `pdf_path` | `str` | — | Path to the PDF file |
| `dpi` | `int` | `200` | Rasterization DPI for scanned pages |
| `pages` | `int \| list[int] \| range \| None` | `None` | 1-based page selection |
| `page_sep` | `str` | `"\n\n"` | Separator inserted between pages |
| `engine` | `ScreenAIEngine \| None` | `None` | Optional reusable engine |

### `ocr_img(image, *, engine=None) -> str`

OCR an image to layout-aware Markdown text.

| Parameter | Type | Description |
| --- | --- | --- |
| `image` | `str \| Path \| PIL.Image \| np.ndarray` | Image source |
| `engine` | `ScreenAIEngine \| None` | Optional reusable engine |

`ocr_img_md` is an identical alias.

### `ScreenAIEngine(dll_path=None)`

Advanced API for custom DLL paths and engine reuse across calls.

## Benchmark It Yourself

The repository includes a reproducible benchmark harness so you can generate numbers on your own machine instead of relying on screenshots.

```bash
python benchmarks/run_benchmark.py img path/to/scan.png --repeat 5
python benchmarks/run_benchmark.py pdf path/to/report.pdf --repeat 3 --pages 1-5
```

See [benchmarks/README.md](benchmarks/README.md) for methodology and external tool comparisons.

## Requirements

| Requirement | Notes |
| --- | --- |
| Windows 10 / 11 | `chrome_screen_ai.dll` is Windows-only |
| Google Chrome | Required for image OCR and scanned / image-only PDFs |
| Python >= 3.9 | Supported in the test matrix |

> `ocr_pdf()` can still extract text-layer PDFs without Chrome Screen AI. The DLL is only required when a page has little or no embedded text and must be OCR'd.

## Verify The Screen AI Component

Open Chrome, go to Settings -> Accessibility, enable any screen-reader-related feature, then confirm that this folder exists:

```text
%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\
```

## Output Format

The Markdown formatter maps visual structure as follows:

| Visual element | Markdown output |
| --- | --- |
| Large font (>= 2x body) | `# Heading` |
| Medium font (1.5-2x body) | `## Heading` |
| Slightly larger font (1.25-1.5x body) | `### Heading` |
| Indented text | leading spaces |
| Multi-column rows (>= 3 rows) | GFM table |
| Formula (`content_type=6`) | `$$...$$` block |

## How It Works

Chrome ships an accessibility component called `chrome_screen_ai.dll`.

This library loads the DLL via `ctypes`, feeds it image data using the `SkBitmap` memory layout reverse-engineered from Chromium and Skia sources, and decodes the returned `VisualAnnotation` protobuf without compiling any `.proto` files.

The bounding-box metadata is then used to reconstruct document structure that most OCR wrappers throw away.

## Project Extras

- [benchmarks/README.md](benchmarks/README.md): reproducible benchmark workflow
- [docs/launch-kit.md](docs/launch-kit.md): maintainer launch copy and post templates
- [screen_ai_pdf_parser.py](screen_ai_pdf_parser.py): legacy compatibility wrapper for older imports

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests that require Chrome's DLL are skipped automatically when the component is not installed.

## License

MIT. See [LICENSE](LICENSE).

`chrome_screen_ai.dll` remains part of Google Chrome and subject to Google's terms. This project does not redistribute or modify the DLL.
