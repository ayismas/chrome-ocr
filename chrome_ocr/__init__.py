"""
chrome-ocr: Local OCR via Chrome's built-in Screen AI engine.

Usage:
    from chrome_ocr import ocr_pdf, ocr_img

    md   = ocr_pdf("scan.pdf")
    text = ocr_img("photo.png")
"""

from importlib.metadata import PackageNotFoundError, version

from .chrome_ocr import ocr_pdf, ocr_img, ocr_img_md, ScreenAIEngine

try:
    __version__ = version("chrome-ocr")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["__version__", "ocr_pdf", "ocr_img", "ocr_img_md", "ScreenAIEngine"]
