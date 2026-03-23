"""
Legacy compatibility wrappers for older screen_ai_pdf_parser imports.

The actively maintained public API lives in the ``chrome_ocr`` package:

    from chrome_ocr import ScreenAIEngine, ocr_img, ocr_pdf

This module remains available so older scripts can continue to import
``ChromeScreenAI``, ``image_to_text()``, and ``pdf_to_markdown()``.
"""

from __future__ import annotations

from typing import Optional, Union

from chrome_ocr import ScreenAIEngine, ocr_img, ocr_pdf

ChromeScreenAI = ScreenAIEngine

__all__ = [
    "ChromeScreenAI",
    "image_to_text",
    "pdf_to_markdown",
]


def image_to_text(image, *, engine: Optional[ChromeScreenAI] = None) -> str:
    """Backward-compatible alias for ``chrome_ocr.ocr_img()``."""
    return ocr_img(image, engine=engine)


def pdf_to_markdown(
    pdf_path: str,
    *,
    dpi: int = 200,
    pages: Optional[Union[int, list[int], range]] = None,
    engine: Optional[ChromeScreenAI] = None,
) -> str:
    """Backward-compatible alias for ``chrome_ocr.ocr_pdf()``."""
    return ocr_pdf(pdf_path, dpi=dpi, pages=pages, engine=engine)
