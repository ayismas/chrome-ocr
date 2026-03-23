# chrome-ocr

Local, offline OCR for Python — powered by Chrome's built-in Screen AI engine.

No API key.  No network call.  No separate model download.
Chrome already ships the model; this library calls it directly.

## Features

- **PDF to Markdown** — text-layer PDFs are extracted instantly; scanned / image PDFs are OCR'd automatically
- **Image to text** — accepts file paths, `PIL.Image`, or NumPy arrays
- **Layout-aware output** — heading hierarchy, paragraph breaks, multi-column tables, and math blocks (`$$...$$`) are inferred from bounding-box geometry
- **Zero extra weight** — reuses Chrome's production-quality ML model (~30 MB, already on disk)
- **Single global engine** — the DLL is loaded once; subsequent calls have negligible overhead

## Requirements

| Requirement | Notes |
| --- | --- |
| Windows 10 / 11 | `chrome_screen_ai.dll` is Windows-only |
| Google Chrome | Required for image OCR and scanned / image-only PDFs; text-layer PDFs can still be extracted without it |
| Python ≥ 3.9 | |

```bash
pip install pillow numpy protobuf   # image OCR
pip install pymupdf                 # PDF support (optional)
```

> **Verify the Screen AI component is present**
> Open Chrome → Settings → Accessibility → enable any screen reader feature,
> then check that `%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\` exists.

> **Note**
> `ocr_pdf()` extracts text-layer PDFs directly via PyMuPDF. Chrome Screen AI is only needed when a page has little or no embedded text and must be OCR'd.

## Quick start

```python
from chrome_ocr import ocr_pdf, ocr_img

# PDF (text-based or scanned) -> Markdown
md = ocr_pdf("report.pdf")

# Image file -> Markdown
text = ocr_img("scan.png")

# PIL Image or NumPy array also accepted
from PIL import Image
text = ocr_img(Image.open("scan.png"))

import numpy as np
text = ocr_img(np.array(Image.open("scan.png")))
```

## API reference

### `ocr_pdf(pdf_path, *, dpi=200, pages=None, page_sep="\n\n", engine=None) -> str`

OCR a PDF to layout-aware Markdown.
Returns only the content extracted from the PDF — no filename header, no `## Page N` markers.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `pdf_path` | `str` | — | Path to the PDF file |
| `dpi` | `int` | `200` | Rasterisation DPI for scanned pages; higher = better quality, slower |
| `pages` | `int \| list[int] \| range \| None` | `None` | 1-based page selection; `None` processes all pages |
| `page_sep` | `str` | `"\n\n"` | Separator inserted between pages; `""` to concatenate without any gap |
| `engine` | `ScreenAIEngine \| None` | `None` | Reuse a custom engine instance; uses the module singleton when `None` |

```python
md = ocr_pdf("report.pdf")                             # all pages
md = ocr_pdf("report.pdf", pages=1)                    # page 1 only
md = ocr_pdf("report.pdf", pages=[1, 3, 5])            # selected pages
md = ocr_pdf("report.pdf", pages=range(1, 11))         # first 10 pages
md = ocr_pdf("report.pdf", dpi=300)                    # higher quality
md = ocr_pdf("report.pdf", page_sep="\n\n---\n\n")     # HR between pages
```

---

### `ocr_img(image, *, engine=None) -> str`

OCR an image to layout-aware Markdown text.

| Parameter | Type | Description |
| --- | --- | --- |
| `image` | `str \| Path \| PIL.Image \| np.ndarray` | Image source |
| `engine` | `ScreenAIEngine \| None` | Optional engine instance |

`ocr_img_md` is an identical alias.

```python
text = ocr_img("photo.png")
text = ocr_img(pil_image)
text = ocr_img(numpy_rgb_array)
```

---

### `ScreenAIEngine(dll_path=None)`

Low-level engine class for advanced use (custom DLL path, per-call engine reuse).

```python
from chrome_ocr import ScreenAIEngine

engine = ScreenAIEngine()          # auto-locate DLL
if engine.ok:
    print(engine.max_dimension)    # max image side length (px)
    text = engine.ocr("page.png")           # plain text
    md   = engine.ocr_markdown("page.png")  # layout-aware Markdown

# Share one engine across many calls
md = ocr_pdf("a.pdf", engine=engine)
md = ocr_pdf("b.pdf", engine=engine)
```

## Output format

Both functions return a Markdown string with layout elements mapped as follows:

| Visual element | Markdown output |
| --- | --- |
| Large font (≥ 2× body) | `# Heading` |
| Medium font (1.5–2×) | `## Heading` |
| Small-large font (1.25–1.5×) | `### Heading` |
| Indented text | leading spaces |
| Multi-column rows (≥ 3 rows) | GFM table |
| Formula (`content_type=6`) | `$$...$$` block |

## Project structure

```text
chrome_ocr/
├── chrome_ocr.py          # core engine + public API
├── __init__.py            # package entry point
├── example/
│   └── demo.ipynb         # interactive walkthrough
└── tests/
    └── test_chrome_ocr.py # pytest suite
```

## How it works

Chrome ships an accessibility component called **Screen AI** (`chrome_screen_ai.dll`).
This library loads the DLL via `ctypes`, feeds it image data using the `SkBitmap` memory
layout reverse-engineered from Chromium/Skia source, and decodes the resulting
protobuf (`VisualAnnotation`) without compiling any `.proto` files.

The bounding-box metadata in the response is used to reconstruct document structure
(headings, paragraphs, tables) that plain OCR tools discard.

## Running tests

```bash
pip install pytest pymupdf pillow numpy protobuf
pytest tests/test_chrome_ocr.py -v
```

Tests that require the DLL are skipped automatically when Chrome is not installed.

## License

MIT — see [LICENSE](LICENSE).

> **Note:** `chrome_screen_ai.dll` is part of Google Chrome and subject to Google's
> terms of service.  This project only loads the DLL that Chrome installs on your
> own machine; it does not distribute or modify the DLL.
