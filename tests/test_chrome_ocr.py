"""
chrome-ocr test suite
=====================
Run with:  pytest tests/ -v

Tests are split into two groups:
  - Unit tests  — pure Python, no DLL, run on any platform / CI
  - Integration — require chrome_screen_ai.dll (Windows + Chrome); auto-skipped otherwise
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

# Ensure the package is importable when running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from chrome_ocr import (  # noqa: E402
    ScreenAIEngine,
    ocr_img,
    ocr_img_md,
    ocr_pdf,
)
from chrome_ocr.chrome_ocr import (  # noqa: E402
    _build_table_block,
    _detect_table,
    _lines_to_markdown,
)

# ---------------------------------------------------------------------------
#  Markers
# ---------------------------------------------------------------------------

_has_dll  = ScreenAIEngine._find_dll() is not None
_has_fitz = importlib.util.find_spec("fitz") is not None

requires_dll  = pytest.mark.skipif(not _has_dll,  reason="chrome_screen_ai.dll not found")
requires_fitz = pytest.mark.skipif(not _has_fitz, reason="pymupdf not installed")


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

def _load_font(size: int):
    """Load an Arial/FreeSans font at *size* pt; fall back to PIL default."""
    candidates = [
        "arial.ttf",           # Windows
        "Arial.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",   # Debian/Ubuntu
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    from PIL import ImageFont
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def _make_text_image(
    text: str = "Hello OCR\nLine two",
    size: tuple[int, int] = (600, 200),
    font_size: int = 28,
) -> Image.Image:
    """White image with *text* rendered at a font size Chrome Screen AI can read."""
    img  = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)
    draw.text((20, 20), text, fill="black", font=font)
    return img


def _make_text_pdf(tmp_path: Path, pages: int = 2) -> Path:
    """Text-layer PDF — PyMuPDF extracts text directly (does NOT trigger OCR)."""
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 60), f"Page {i + 1} — chrome-ocr test document", fontsize=14)
        page.insert_text((60, 90), "The quick brown fox jumps over the lazy dog.", fontsize=12)
    path = tmp_path / "text_layer.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _make_image_only_pdf(tmp_path: Path, text: str = "chrome ocr works") -> Path:
    """Scanned-style PDF: text is rasterised into an image with no text layer.

    This forces pdf_to_markdown() to take the OCR path (Chrome Screen AI),
    because page.get_text() returns an empty string for image-only pages.
    """
    import io
    import fitz

    # Render text into a high-resolution image
    img = _make_text_image(text, size=(1200, 400), font_size=48)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    doc  = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insert as embedded image — no text layer is created
    page.insert_image(
        fitz.Rect(30, 30, 565, 220),
        stream=buf.read(),
    )
    path = tmp_path / "scanned.pdf"
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
#  Unit tests — layout formatter
# ---------------------------------------------------------------------------

class TestLinestoMarkdown:

    @staticmethod
    def _line(text, x=10, y=0, w=200, h=12, block=0, para=0, ct=0, conf=1.0):
        return {
            "text": text,
            "bbox": {"x": x, "y": y, "w": w, "h": h},
            "block_id": block,
            "paragraph_id": para,
            "content_type": ct,
            "confidence": conf,
        }

    def test_empty_input(self):
        assert _lines_to_markdown([]) == ""

    def test_whitespace_only_filtered(self):
        lines = [self._line("   "), self._line("hello")]
        assert _lines_to_markdown(lines) == "hello"

    def test_heading_h1(self):
        # Font height >= 2x median -> H1
        lines = [self._line("Big Title", h=30), self._line("body text", h=12)]
        md = _lines_to_markdown(lines)
        assert md.startswith("# Big Title")

    def test_heading_h2(self):
        lines = [self._line("Section", h=20), self._line("body text", h=12)]
        md = _lines_to_markdown(lines)
        assert md.startswith("## Section")

    def test_heading_h3(self):
        lines = [self._line("Subsection", h=16), self._line("body text", h=12)]
        md = _lines_to_markdown(lines)
        assert md.startswith("### Subsection")

    def test_formula_wrapped_in_dollars(self):
        lines = [self._line(r"E = mc^2", ct=6, h=12)]
        md = _lines_to_markdown(lines)
        assert "$$" in md
        assert r"E = mc^2" in md

    def test_block_change_inserts_blank_line(self):
        lines = [
            self._line("Para A", block=0, para=0, y=0),
            self._line("Para B", block=1, para=0, y=20),
        ]
        md = _lines_to_markdown(lines)
        assert "\n\n" in md

    def test_paragraph_change_inserts_blank_line(self):
        lines = [
            self._line("Para A", block=0, para=0, y=0),
            self._line("Para B", block=0, para=1, y=20),
        ]
        md = _lines_to_markdown(lines)
        assert "\n\n" in md

    def test_single_line(self):
        lines = [self._line("Just one line")]
        assert _lines_to_markdown(lines) == "Just one line"

    def test_no_extra_blank_lines(self):
        lines = [self._line(f"Line {i}", y=i * 15) for i in range(5)]
        md = _lines_to_markdown(lines)
        assert "\n\n\n" not in md


class TestPublicAliases:

    def test_ocr_img_md_is_alias(self):
        assert ocr_img_md is ocr_img


# ---------------------------------------------------------------------------
#  Unit tests — table detection
# ---------------------------------------------------------------------------

class TestTableDetection:

    @staticmethod
    def _line(text, x, y, h=12):
        return {
            "text": text,
            "bbox": {"x": x, "y": y, "w": 80, "h": h},
            "block_id": 0, "paragraph_id": 0,
            "content_type": 0, "confidence": 1.0,
        }

    def test_single_column_no_table(self):
        lines = [self._line(f"row {i}", x=10, y=i * 16) for i in range(5)]
        assert _detect_table(lines, 12) == {}

    def test_two_col_four_rows_detected(self):
        lines = []
        for row in range(4):
            lines.append(self._line(f"L{row}", x=10,  y=row * 16))
            lines.append(self._line(f"R{row}", x=200, y=row * 16))
        result = _detect_table(lines, 12)
        assert len(result) > 0

    def test_fewer_than_three_rows_not_table(self):
        lines = []
        for row in range(2):
            lines.append(self._line(f"L{row}", x=10,  y=row * 16))
            lines.append(self._line(f"R{row}", x=200, y=row * 16))
        result = _detect_table(lines, 12)
        assert result == {}


class TestBuildTableBlock:

    @staticmethod
    def _line(text, x, y, h=12):
        return {
            "text": text,
            "bbox": {"x": x, "y": y, "w": 80, "h": h},
            "block_id": 0, "paragraph_id": 0,
            "content_type": 0, "confidence": 1.0,
        }

    def test_single_column_returns_empty(self):
        lines = [self._line("only", 10, 0)]
        assert _build_table_block(lines, [[0]], {}) == []

    def test_gfm_separator_row_present(self):
        lines = [
            self._line("Name",  10, 0),  self._line("Value",  200, 0),
            self._line("alpha", 10, 16), self._line("1",      200, 16),
            self._line("beta",  10, 32), self._line("2",      200, 32),
        ]
        rows = [[0, 1], [2, 3], [4, 5]]
        md = _build_table_block(lines, rows, {})
        assert any("---" in row for row in md)

    def test_column_headers_in_first_row(self):
        lines = [
            self._line("A", 10, 0), self._line("B", 200, 0),
            self._line("1", 10, 16), self._line("2", 200, 16),
            self._line("3", 10, 32), self._line("4", 200, 32),
        ]
        rows = [[0, 1], [2, 3], [4, 5]]
        md = _build_table_block(lines, rows, {})
        assert "A" in md[0] and "B" in md[0]

    def test_ragged_rows_padded(self):
        # Row 0 has 2 cols, row 1 has 1 col — should be padded
        lines = [
            self._line("H1", 10, 0), self._line("H2", 200, 0),
            self._line("only", 10, 16),
            self._line("full1", 10, 32), self._line("full2", 200, 32),
        ]
        rows = [[0, 1], [2], [3, 4]]
        md = _build_table_block(lines, rows, {})
        # Every row should have the same number of | delimiters
        pipe_counts = [row.count("|") for row in md if "---" not in row]
        assert len(set(pipe_counts)) == 1


# ---------------------------------------------------------------------------
#  Integration tests — require chrome_screen_ai.dll
# ---------------------------------------------------------------------------

class TestScreenAIEngine:

    @requires_dll
    def test_engine_initialises(self):
        e = ScreenAIEngine()
        assert e.ok
        assert e.max_dimension > 0

    @requires_dll
    def test_ocr_white_image_returns_string(self):
        e   = ScreenAIEngine()
        img = np.full((80, 200, 3), 255, dtype=np.uint8)
        assert isinstance(e.ocr(img), str)

    @requires_dll
    def test_ocr_markdown_white_image_returns_string(self):
        e   = ScreenAIEngine()
        img = np.full((80, 200, 3), 255, dtype=np.uint8)
        assert isinstance(e.ocr_markdown(img), str)

    @requires_dll
    def test_unready_engine_raises(self):
        e = ScreenAIEngine(dll_path="/nonexistent/chrome_screen_ai.dll")
        assert not e.ok
        with pytest.raises(RuntimeError):
            e.ocr("any.png")


class TestPublicAPI:

    @requires_dll
    def test_image_to_text_from_path(self, tmp_path):
        path = tmp_path / "white.png"
        Image.new("RGB", (200, 80), "white").save(path)
        result = ocr_img(str(path))
        assert isinstance(result, str)

    @requires_dll
    def test_image_to_text_from_pil(self):
        assert isinstance(ocr_img(_make_text_image()), str)

    @requires_dll
    def test_image_to_text_from_numpy(self):
        arr = np.array(_make_text_image())
        assert isinstance(ocr_img(arr), str)

    @requires_dll
    def test_image_with_text_produces_nonempty_result(self):
        img    = _make_text_image("Hello OCR world")
        result = ocr_img(img)
        assert result.strip() != ""

    @requires_fitz
    @requires_dll
    def test_pdf_all_pages_returns_content(self, tmp_path):
        # _make_text_pdf embeds "quick brown fox" on every page
        path = _make_text_pdf(tmp_path, pages=3)
        md   = ocr_pdf(str(path))
        assert "quick brown fox" in md.lower()
        # No injected page headers
        assert "## Page" not in md
        assert f"# {path.stem}" not in md

    @requires_fitz
    @requires_dll
    def test_pdf_single_page_no_other_pages(self, tmp_path):
        # Each page in _make_text_pdf contains its 1-based page number
        path = _make_text_pdf(tmp_path, pages=3)
        md   = ocr_pdf(str(path), pages=1)
        # Page 1 text is present; page 2 and 3 text should NOT be
        assert "Page 1" in md
        assert "Page 2" not in md
        assert "Page 3" not in md

    @requires_fitz
    @requires_dll
    def test_pdf_page_list(self, tmp_path):
        path = _make_text_pdf(tmp_path, pages=4)
        md   = ocr_pdf(str(path), pages=[1, 3])
        assert "Page 1" in md
        assert "Page 3" in md
        assert "Page 2" not in md
        assert "Page 4" not in md

    @requires_fitz
    @requires_dll
    def test_pdf_page_range(self, tmp_path):
        path = _make_text_pdf(tmp_path, pages=5)
        md   = ocr_pdf(str(path), pages=range(1, 4))
        assert "Page 3" in md
        assert "Page 4" not in md

    @requires_fitz
    @requires_dll
    def test_pdf_no_injected_headers(self, tmp_path):
        """Output must contain only PDF content — no library-added headers."""
        path = _make_text_pdf(tmp_path, pages=2)
        md   = ocr_pdf(str(path))
        assert "## Page" not in md
        assert f"# {path.stem}" not in md

    @requires_fitz
    @requires_dll
    def test_pdf_page_sep_custom(self, tmp_path):
        """page_sep is inserted between pages and nowhere else."""
        path = _make_text_pdf(tmp_path, pages=2)
        sep  = "<<<PAGE_BREAK>>>"
        md   = ocr_pdf(str(path), page_sep=sep)
        assert md.count(sep) == 1   # exactly one separator for two pages

    @requires_fitz
    @requires_dll
    def test_pdf_page_sep_empty(self, tmp_path):
        """page_sep='' concatenates pages with no separator."""
        path = _make_text_pdf(tmp_path, pages=2)
        md   = ocr_pdf(str(path), page_sep="")
        assert isinstance(md, str) and len(md) > 0

    @requires_fitz
    @requires_dll
    def test_shared_engine_across_calls(self, tmp_path):
        path   = _make_text_pdf(tmp_path, pages=2)
        engine = ScreenAIEngine()
        md1 = ocr_pdf(str(path), pages=1, engine=engine)
        md2 = ocr_pdf(str(path), pages=2, engine=engine)
        assert "Page 1" in md1
        assert "Page 2" in md2


# ---------------------------------------------------------------------------
#  OCR accuracy tests — verify that recognised text matches rendered text
#
#  Chrome Screen AI is a production-quality model; on clean, high-contrast
#  images it should achieve near-100% accuracy on simple Latin words.
#  We use case-insensitive substring matching to tolerate minor variations.
# ---------------------------------------------------------------------------

class TestOCRAccuracy:
    """Real OCR round-trip: render text -> run OCR -> verify words are present."""

    WORDS = ["hello", "world", "chrome", "ocr", "test"]

    @requires_dll
    def test_image_file_recognised(self, tmp_path):
        text = "Hello World\nChrome OCR Test"
        path = tmp_path / "words.png"
        _make_text_image(text).save(path)

        result = ocr_img(str(path)).lower()
        found  = [w for w in self.WORDS if w in result]
        assert len(found) >= 3, (
            f"Expected at least 3 of {self.WORDS} in OCR output, got {found!r}.\n"
            f"Full output: {result!r}"
        )

    @requires_dll
    def test_pil_image_recognised(self):
        text   = "Hello World\nChrome OCR Test"
        img    = _make_text_image(text)
        result = ocr_img(img).lower()
        found  = [w for w in self.WORDS if w in result]
        assert len(found) >= 3, (
            f"Expected at least 3 of {self.WORDS} in OCR output, got {found!r}.\n"
            f"Full output: {result!r}"
        )

    @requires_dll
    def test_numpy_array_recognised(self):
        text   = "Hello World\nChrome OCR Test"
        arr    = np.array(_make_text_image(text))
        result = ocr_img(arr).lower()
        found  = [w for w in self.WORDS if w in result]
        assert len(found) >= 3, (
            f"Expected at least 3 of {self.WORDS} in OCR output, got {found!r}.\n"
            f"Full output: {result!r}"
        )

    @requires_dll
    def test_multiline_text_preserved(self):
        """Each line of the input should produce at least one recognisable word."""
        lines  = ["First Line Alpha", "Second Line Beta", "Third Line Gamma"]
        img    = _make_text_image("\n".join(lines), size=(700, 300), font_size=32)
        result = ocr_img(img).lower()
        for keyword in ["first", "second", "third"]:
            assert keyword in result, (
                f"Expected {keyword!r} in OCR output.\nFull output: {result!r}"
            )

    @requires_dll
    def test_digits_recognised(self):
        """Digits (0-9) should survive the OCR round-trip."""
        text   = "0 1 2 3 4 5 6 7 8 9"
        img    = _make_text_image(text, size=(600, 120), font_size=36)
        result = ocr_img(img)
        digits_found = [d for d in "0123456789" if d in result]
        assert len(digits_found) >= 7, (
            f"Expected >= 7 digits, got {digits_found!r}.\nFull output: {result!r}"
        )


# ---------------------------------------------------------------------------
#  Image-only PDF tests — verify the OCR path inside ocr_pdf()
#
#  These PDFs have no text layer, so PyMuPDF returns "" for get_text().
#  ocr_pdf() must fall through to Chrome Screen AI OCR.
# ---------------------------------------------------------------------------

class TestImageOnlyPDF:
    """End-to-end: scanned-style PDF (no text layer) -> OCR -> Markdown."""

    @requires_fitz
    @requires_dll
    def test_ocr_path_triggered(self, tmp_path):
        """Verify that an image-only page actually goes through OCR (non-empty result)."""
        path = _make_image_only_pdf(tmp_path, text="chrome ocr works")
        md   = ocr_pdf(str(path))
        # Direct text extraction returns ""; OCR must have produced something.
        assert len(md.strip()) > 5, (
            f"OCR path returned almost nothing; OCR may not have run.\n"
            f"Full output: {md!r}"
        )
        # No injected structural headers
        assert "## Page" not in md

    @requires_fitz
    @requires_dll
    def test_ocr_words_readable(self, tmp_path):
        """OCR on an image-only PDF should recover the rendered words."""
        target_words = ["chrome", "ocr", "works"]
        path   = _make_image_only_pdf(tmp_path, text="Chrome OCR Works")
        result = ocr_pdf(str(path)).lower()
        found  = [w for w in target_words if w in result]
        assert len(found) >= 2, (
            f"Expected >= 2 of {target_words} in result, got {found!r}.\n"
            f"Full output: {result!r}"
        )

    @requires_fitz
    @requires_dll
    def test_text_pdf_does_not_use_ocr(self, tmp_path):
        """Text-layer PDF should extract directly and still produce correct output."""
        path   = _make_text_pdf(tmp_path, pages=1)
        md     = ocr_pdf(str(path))
        result = md.lower()
        assert "quick brown fox" in result, (
            f"Direct text extraction failed.\nFull output: {result!r}"
        )

    @requires_fitz
    @requires_dll
    def test_mixed_pdf_handles_both_page_types(self, tmp_path):
        """A PDF mixing text pages and image-only pages should handle both."""
        import fitz, io
        doc = fitz.open()

        # Page 1: text layer (direct extraction)
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((60, 60), "Text layer page content here.", fontsize=14)

        # Page 2: image only (OCR)
        p2  = doc.new_page(width=595, height=842)
        img = _make_text_image("Scanned page content", size=(1000, 200), font_size=40)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        p2.insert_image(fitz.Rect(30, 30, 565, 180), stream=buf.read())

        path = tmp_path / "mixed.pdf"
        doc.save(str(path))
        doc.close()

        md = ocr_pdf(str(path))
        assert "text layer" in md.lower()
        assert "## Page" not in md
