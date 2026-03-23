"""
chrome-ocr: Local OCR via Chrome's built-in Screen AI engine.

Usage:
    from chrome_ocr import ocr_pdf, ocr_img

    md   = ocr_pdf("scan.pdf")
    text = ocr_img("photo.png")
"""

from .chrome_ocr import ocr_pdf, ocr_img, ocr_img_md, ScreenAIEngine

__all__ = ["ocr_pdf", "ocr_img", "ocr_img_md", "ScreenAIEngine"]
