"""
chrome-ocr: Local OCR via Chrome's built-in Screen AI engine.

Calls chrome_screen_ai.dll directly via ctypes, feeding raw SkBitmap memory
as reverse-engineered from Chromium/Skia source.  No API key, no network,
no separate model download — Chrome already ships the model.

Quick start
-----------
    from chrome_ocr import ocr_pdf, ocr_img

    md   = ocr_pdf("scan.pdf")          # PDF  -> layout-aware Markdown
    text = ocr_img("photo.png")           # image file -> Markdown
    text = ocr_img(pil_image)             # PIL Image  -> Markdown
    text = ocr_img(numpy_rgb_array)       # ndarray    -> Markdown

Requirements
------------
- Windows 10/11 with Google Chrome installed (Screen AI component auto-downloaded
  by Chrome for accessibility features; usually present after first launch).
- pip install pymupdf pillow numpy protobuf
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
from glob import glob
from pathlib import Path
from typing import Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Minimal protobuf wire-format decoder  (no .proto compilation needed)
# ---------------------------------------------------------------------------

def _decode_msg(buf: bytes) -> dict[int, list]:
    from google.protobuf.internal.decoder import _DecodeVarint32
    fields: dict[int, list] = {}
    i = 0
    while i < len(buf):
        tag, i = _DecodeVarint32(buf, i)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            val, i = _DecodeVarint32(buf, i)
        elif wt == 1:
            val = struct.unpack_from('<d', buf, i)[0]; i += 8
        elif wt == 2:
            length, i = _DecodeVarint32(buf, i)
            val = buf[i:i + length]; i += length
        elif wt == 5:
            val = struct.unpack_from('<f', buf, i)[0]; i += 4
        else:
            break
        fields.setdefault(fn, []).append((wt, val))
    return fields


def _parse_rect(data: bytes) -> dict:
    f = _decode_msg(data)
    return {
        "x": f.get(1, [(0, 0)])[0][1],
        "y": f.get(2, [(0, 0)])[0][1],
        "w": f.get(3, [(0, 0)])[0][1],
        "h": f.get(4, [(0, 0)])[0][1],
    }


def _parse_visual_annotation(data: bytes) -> list[dict]:
    """Parse a VisualAnnotation protobuf into a list of line dicts.

    Each dict contains: text, bbox, block_id, paragraph_id,
    content_type (0=printed, 1=handwritten, 6=formula), confidence.
    """
    lines = []
    for _, ld in _decode_msg(data).get(2, []):       # field 2 = repeated LineBox
        if not isinstance(ld, bytes):
            continue
        lf = _decode_msg(ld)

        text = ""
        if 3 in lf and isinstance(lf[3][0][1], bytes):
            text = lf[3][0][1].decode("utf-8", "replace")

        bbox = {"x": 0, "y": 0, "w": 0, "h": 0}
        if 2 in lf and isinstance(lf[2][0][1], bytes):
            bbox = _parse_rect(lf[2][0][1])

        lines.append({
            "text":         text,
            "bbox":         bbox,
            "block_id":     lf[5][0][1]  if 5  in lf else -1,
            "paragraph_id": lf[11][0][1] if 11 in lf else -1,
            "content_type": lf[8][0][1]  if 8  in lf else 0,
            "confidence":   lf[10][0][1] if 10 in lf else 0.0,
        })
    return lines


# ---------------------------------------------------------------------------
#  Layout-aware Markdown formatter
# ---------------------------------------------------------------------------

def _lines_to_markdown(lines: list[dict]) -> str:
    """Convert OCR lines with bounding-box metadata into layout-aware Markdown.

    Heuristics applied
    ------------------
    - Font height vs. median height  -> heading level (# / ## / ###)
    - block_id / paragraph_id changes -> blank-line paragraph breaks
    - x-offset from left margin      -> indentation
    - Same-row multi-column groups   -> Markdown tables
    - content_type == 6              -> $$...$$ math blocks
    """
    if not lines:
        return ""

    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return ""

    heights = [l["bbox"]["h"] for l in lines if l["bbox"]["h"] > 0]
    if not heights:
        return "\n".join(l["text"] for l in lines)

    median_h = sorted(heights)[len(heights) // 2]

    x_vals = [l["bbox"]["x"] for l in lines if l["bbox"]["x"] > 0]
    base_x = min(x_vals) if x_vals else 0

    table_rows = _detect_table(lines, median_h)

    parts: list[str] = []
    prev_block = -1
    prev_para  = -1
    prev_y_bottom = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        if table_rows and i in table_rows:
            row_indices = table_rows[i]
            table_md = _build_table_block(lines, row_indices, table_rows)
            if table_md:
                if parts and parts[-1] != "":
                    parts.append("")
                parts.extend(table_md)
                parts.append("")
                consumed = set()
                for ri in row_indices:
                    consumed.update(ri)
                i = max(consumed) + 1
                continue

        text     = line["text"].strip()
        bbox     = line["bbox"]
        h        = bbox["h"]
        block_id = line["block_id"]
        para_id  = line["paragraph_id"]
        ct       = line["content_type"]

        y_gap         = bbox["y"] - prev_y_bottom if prev_y_bottom > 0 else 0
        block_changed = block_id != prev_block and prev_block != -1
        para_changed  = para_id  != prev_para  and prev_para  != -1

        if block_changed and parts and parts[-1] != "":
            parts.append("")
        elif para_changed and not block_changed:
            if parts and parts[-1] != "":
                parts.append("")
        elif y_gap > median_h * 1.5 and parts and parts[-1] != "":
            parts.append("")

        if ct == 6:
            parts.append(f"$$\n{text}\n$$")
        elif h > 0 and median_h > 0:
            ratio = h / median_h
            if ratio >= 2.0:
                parts.append(f"# {text}")
            elif ratio >= 1.5:
                parts.append(f"## {text}")
            elif ratio >= 1.25:
                parts.append(f"### {text}")
            else:
                indent = bbox["x"] - base_x
                parts.append(f"  {text}" if indent > median_h * 2 else text)
        else:
            parts.append(text)

        prev_y_bottom = bbox["y"] + h
        prev_block    = block_id
        prev_para     = para_id
        i += 1

    result = "\n".join(parts)
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result.strip()


def _detect_table(lines: list[dict], median_h: float) -> dict[int, list[list[int]]]:
    """Detect table regions.  Returns {start_line_index: [[row1_cols], [row2_cols], ...]}."""
    if len(lines) < 3:
        return {}

    rows: list[list[int]] = []
    current_row = [0]
    for i in range(1, len(lines)):
        y_diff = abs(lines[i]["bbox"]["y"] - lines[current_row[0]]["bbox"]["y"])
        if y_diff < median_h * 0.7:
            current_row.append(i)
        else:
            rows.append(current_row)
            current_row = [i]
    rows.append(current_row)

    multi_col_rows = []
    for row in rows:
        if len(row) >= 2:
            multi_col_rows.append(row)
        else:
            if len(multi_col_rows) >= 3:
                return {multi_col_rows[0][0]: multi_col_rows}
            multi_col_rows = []

    if len(multi_col_rows) >= 3:
        return {multi_col_rows[0][0]: multi_col_rows}
    return {}


def _build_table_block(
    lines: list[dict], row_indices: list[list[int]], table_rows: dict
) -> list[str]:
    """Render detected table rows as a GitHub-flavoured Markdown table."""
    if not row_indices:
        return []

    max_cols = max(len(row) for row in row_indices)
    if max_cols < 2:
        return []

    md_lines = []
    for ri, row in enumerate(row_indices):
        sorted_cells = sorted(row, key=lambda idx: lines[idx]["bbox"]["x"])
        cells = [lines[idx]["text"].strip() for idx in sorted_cells]
        while len(cells) < max_cols:
            cells.append("")
        md_lines.append("| " + " | ".join(cells) + " |")
        if ri == 0:
            md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")

    return md_lines


# ---------------------------------------------------------------------------
#  Chrome Screen AI DLL wrapper
# ---------------------------------------------------------------------------

_CB_SIZE    = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_char_p)
_CB_CONTENT = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p)

# DLL-path -> (dll, max_dim, refs) — prevents calling InitOCRUsingCallback twice.
# Chrome's Screen AI DLL must only be initialised once per process; a second call
# corrupts the engine's internal state and causes a segfault / kernel crash.
_dll_registry: dict = {}


class ScreenAIEngine:
    """Wrapper around Chrome's ``chrome_screen_ai.dll``.

    Multiple ``ScreenAIEngine`` instances created with the same DLL path share
    one underlying initialised DLL (tracked in the module-level registry).
    This is safe and avoids the crash that would result from calling
    ``InitOCRUsingCallback`` more than once per process.

    Parameters
    ----------
    dll_path:
        Explicit path to ``chrome_screen_ai.dll``.  If *None*, the engine
        searches the default Chrome user-data location automatically.

    Examples
    --------
    >>> engine = ScreenAIEngine()
    >>> if engine.ok:
    ...     text = engine.ocr_markdown("page.png")
    """

    _kBGRA_8888 = 6
    _kPremul    = 2

    def __init__(self, dll_path: Optional[str] = None):
        self._dll     = None
        self._ready   = False
        self._max_dim = 0
        self._refs: list = []   # keep ctypes callbacks / buffers alive

        resolved = dll_path or self._find_dll()
        if not resolved:
            logger.warning("chrome_screen_ai.dll not found — is Chrome installed?")
            return

        # Reuse an already-initialised DLL instead of calling InitOCRUsingCallback again.
        if resolved in _dll_registry:
            cached = _dll_registry[resolved]
            self._dll, self._max_dim, self._refs = cached["dll"], cached["max_dim"], cached["refs"]
            self._ready = True
            logger.debug("ScreenAIEngine reusing cached DLL: %s", resolved)
            return

        dll_dir = str(Path(resolved).parent)
        try:
            dll = ctypes.CDLL(resolved)
            self._setup(dll, dll_dir, dll_path=resolved)
        except Exception as e:
            logger.error("ScreenAIEngine init failed: %s", e)

    # -- DLL discovery -------------------------------------------------------

    @staticmethod
    def _find_dll() -> Optional[str]:
        pattern = os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\*\chrome_screen_ai.dll"
        )
        hits = sorted(glob(pattern), reverse=True)
        return hits[0] if hits else None

    # -- Initialisation ------------------------------------------------------

    def _setup(self, dll, dll_dir: str, dll_path: str):
        def _size(p: bytes) -> int:
            try:
                fp = os.path.join(dll_dir, p.decode())
                return os.path.getsize(fp) if os.path.exists(fp) else 0
            except Exception:
                return 0

        def _read(p: bytes, sz: int, buf):
            try:
                with open(os.path.join(dll_dir, p.decode()), "rb") as f:
                    ctypes.memmove(buf, f.read(sz), sz)
            except Exception:
                pass

        cb_s, cb_r = _CB_SIZE(_size), _CB_CONTENT(_read)
        self._refs.extend([cb_s, cb_r])
        dll.SetFileContentFunctions(cb_s, cb_r)

        dll.InitOCRUsingCallback.argtypes = []
        dll.InitOCRUsingCallback.restype  = ctypes.c_bool
        if not dll.InitOCRUsingCallback():
            logger.error("InitOCRUsingCallback returned False")
            return

        dll.GetMaxImageDimension.argtypes = []
        dll.GetMaxImageDimension.restype  = ctypes.c_uint32
        self._max_dim = dll.GetMaxImageDimension()

        dll.PerformOCR.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        dll.PerformOCR.restype  = ctypes.c_void_p
        dll.FreeLibraryAllocatedCharArray.argtypes = [ctypes.c_void_p]
        dll.FreeLibraryAllocatedCharArray.restype  = None

        dll.GetLibraryVersion.argtypes = [ctypes.POINTER(ctypes.c_uint32)] * 2
        dll.GetLibraryVersion.restype  = None
        ma, mi = ctypes.c_uint32(), ctypes.c_uint32()
        dll.GetLibraryVersion(ctypes.byref(ma), ctypes.byref(mi))

        self._dll   = dll
        self._ready = True
        logger.info("ScreenAI v%d.%d ready (max %dpx)", ma.value, mi.value, self._max_dim)

        # Register so subsequent ScreenAIEngine() calls reuse this DLL.
        _dll_registry[dll_path] = {
            "dll":     dll,
            "max_dim": self._max_dim,
            "refs":    self._refs,   # keep callbacks alive for the process lifetime
        }

    # -- Public API ----------------------------------------------------------

    @property
    def ok(self) -> bool:
        """True if the DLL loaded and the OCR engine initialised successfully."""
        return self._ready

    @property
    def max_dimension(self) -> int:
        """Maximum image side length accepted by the engine (pixels)."""
        return self._max_dim

    def ocr(self, image) -> str:
        """Return plain text (no layout) for *image*."""
        if not self._ready:
            raise RuntimeError("ScreenAIEngine is not ready")
        bgra, w, h = self._to_bgra(image)
        proto = self._call_dll(bgra, w, h)
        if not proto:
            return ""
        return "\n".join(l["text"] for l in _parse_visual_annotation(proto) if l["text"].strip())

    def ocr_markdown(self, image) -> str:
        """Return layout-aware Markdown for *image* (headings, tables, math)."""
        if not self._ready:
            raise RuntimeError("ScreenAIEngine is not ready")
        bgra, w, h = self._to_bgra(image)
        proto = self._call_dll(bgra, w, h)
        if not proto:
            return ""
        return _lines_to_markdown(_parse_visual_annotation(proto))

    # -- Internal helpers ----------------------------------------------------

    def _to_bgra(self, image) -> tuple[np.ndarray, int, int]:
        """Normalise any supported image input to a BGRA uint8 ndarray."""
        from PIL import Image as PILImage

        if isinstance(image, (str, Path)):
            image = PILImage.open(str(image))
        elif isinstance(image, np.ndarray):
            image = PILImage.fromarray(image)

        image = image.convert("RGB")
        w, h  = image.size

        if self._max_dim and max(w, h) > self._max_dim:
            r    = self._max_dim / max(w, h)
            w, h = int(w * r), int(h * r)
            image = image.resize((w, h), PILImage.LANCZOS)

        rgb  = np.asarray(image)
        bgra = np.empty((h, w, 4), np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        bgra[..., 3] = 255
        return np.ascontiguousarray(bgra), w, h

    def _call_dll(self, bgra: np.ndarray, w: int, h: int) -> bytes:
        """Call PerformOCR and return the raw protobuf bytes."""
        row_bytes = w * 4
        pix_buf   = (ctypes.c_uint8 * bgra.nbytes).from_buffer(bgra)
        pix_ptr   = ctypes.cast(pix_buf, ctypes.c_void_p).value

        # Minimal SkPixelRef stub — only needs to be non-NULL for isNull() check
        pr = bytearray(48)
        struct.pack_into("<Qi", pr, 0,  0, 999999)
        struct.pack_into("<iiQQ", pr, 16, w, h, pix_ptr, row_bytes)
        pr_buf = (ctypes.c_uint8 * 48)(*pr)
        self._refs.append(pr_buf)

        # SkBitmap layout reverse-engineered from Chromium/Skia
        bm = bytearray(48)
        struct.pack_into("<QQQ",  bm, 0,  ctypes.cast(pr_buf, ctypes.c_void_p).value, pix_ptr, row_bytes)
        struct.pack_into("<Qii", bm, 24, 0, self._kBGRA_8888, self._kPremul)
        struct.pack_into("<ii",  bm, 40, w, h)
        bm_buf = (ctypes.c_uint8 * 48)(*bm)

        alen = ctypes.c_uint32(0)
        rp   = self._dll.PerformOCR(ctypes.cast(bm_buf, ctypes.c_void_p), ctypes.byref(alen))
        if not rp or not alen.value:
            return b""

        proto = bytes((ctypes.c_char * alen.value).from_address(rp))
        self._dll.FreeLibraryAllocatedCharArray(rp)
        return proto


# ---------------------------------------------------------------------------
#  Module-level singleton  (model loads once; all subsequent calls are free)
# ---------------------------------------------------------------------------

_engine: Optional[ScreenAIEngine] = None


def _get_engine() -> ScreenAIEngine:
    global _engine
    if _engine is None:
        _engine = ScreenAIEngine()
    if not _engine.ok:
        raise RuntimeError(
            "Chrome Screen AI is unavailable.  "
            "Make sure Google Chrome is installed and the screen_ai component "
            "has been downloaded (Chrome > Settings > Accessibility)."
        )
    return _engine


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def ocr_img(
    image,
    *,
    engine: Optional[ScreenAIEngine] = None,
) -> str:
    """OCR an image to layout-aware Markdown text via Chrome Screen AI.

    Parameters
    ----------
    image:
        A file path (``str`` / ``pathlib.Path``), a ``PIL.Image.Image``,
        or a NumPy ``ndarray`` in RGB order.
    engine:
        Optional pre-constructed :class:`ScreenAIEngine`.  Uses the
        module-level singleton when *None*.

    Returns
    -------
    str
        Markdown string preserving headings, paragraphs, tables, and
        math blocks (``$$...$$``) detected from the image layout.

    Examples
    --------
    >>> text = ocr_img("scan.png")
    >>> text = ocr_img(pil_image)
    >>> text = ocr_img(numpy_rgb_array)
    """
    return (engine or _get_engine()).ocr_markdown(image)


#: Alias — identical to :func:`ocr_img` but emphasises the Markdown output.
ocr_img_md = ocr_img


def ocr_pdf(
    pdf_path: str,
    *,
    dpi: int = 200,
    pages: Optional[Union[int, list[int], range]] = None,
    page_sep: str = "\n\n",
    engine: Optional[ScreenAIEngine] = None,
) -> str:
    """OCR a PDF to layout-aware Markdown text.

    Returns only the content extracted from the PDF — no filename headers,
    no ``## Page N`` markers, and no decorations added by this library.
    For text-based PDFs the text layer is extracted directly (fast).
    For scanned / image-only PDFs each page is rasterised and fed to the
    Chrome Screen AI OCR engine.

    Parameters
    ----------
    pdf_path:
        Path to the PDF file.
    dpi:
        Rasterisation resolution for scanned pages.  Higher values improve
        accuracy at the cost of speed.  Default: ``200``.
    pages:
        Page selection (1-based).
        ``None`` processes all pages.
        An ``int`` selects a single page.
        A ``list[int]`` or ``range`` selects specific pages.
    page_sep:
        String inserted between pages when the result spans multiple pages.
        Default: ``"\\n\\n"`` (blank line).  Use ``"\\n\\n---\\n\\n"`` for
        a horizontal rule, or ``""`` to concatenate without any separator.
    engine:
        Optional pre-constructed :class:`ScreenAIEngine`.  Uses the
        module-level singleton when *None*.

    Returns
    -------
    str
        Markdown text of the selected pages, joined by *page_sep*.

    Examples
    --------
    >>> md = ocr_pdf("report.pdf")
    >>> md = ocr_pdf("report.pdf", pages=range(1, 11))   # first 10 pages
    >>> md = ocr_pdf("report.pdf", pages=[1, 3, 5])      # selected pages
    >>> md = ocr_pdf("report.pdf", dpi=300)              # higher quality
    >>> md = ocr_pdf("report.pdf", page_sep="\\n\\n---\\n\\n")  # HR between pages
    """
    try:
        import fitz
    except ImportError:
        raise ImportError(
            "ocr_pdf() requires PyMuPDF.  "
            "Install it with: pip install pymupdf"
        ) from None

    ai    = engine or _get_engine()
    doc   = fitz.open(pdf_path)
    total = len(doc)

    # Normalise page selection (external 1-based -> internal 0-based)
    if pages is None:
        indices = range(total)
    elif isinstance(pages, int):
        indices = [pages - 1]
    else:
        indices = [p - 1 for p in pages]
    indices = [i for i in indices if 0 <= i < total]

    max_dim = ai.max_dimension or 2048
    parts: list[str] = []

    for idx in indices:
        page     = doc[idx]
        raw_text = page.get_text().strip()

        if len(raw_text) <= 50:
            # Scanned page — rasterise then OCR
            scale = min(dpi / 72, max_dim / max(page.rect.width, page.rect.height))
            pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            from PIL import Image
            img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = ai.ocr_markdown(img)
        else:
            text = raw_text

        parts.append(text)

        if len(parts) % 20 == 0:
            logger.info("  %d / %d pages processed", len(parts), len(indices))

    doc.close()

    return page_sep.join(parts)
