"""
Chrome Screen AI OCR Engine

基于 Chrome 浏览器内置 Screen AI (chrome_screen_ai.dll) 实现的本地 OCR，
通过逆向 Chromium/Skia 源码中 SkBitmap 的内存布局直接调用 DLL。

Usage:
    from pdf_parser import pdf_to_markdown, image_to_text

    md   = pdf_to_markdown("scan.pdf")        # PDF → Markdown (排版感知)
    text = image_to_text("photo.png")          # 图片 → Markdown
    text = image_to_text(pil_image)            # PIL Image → Markdown
    text = image_to_text(numpy_rgb_array)      # ndarray  → Markdown
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

# ────────────────────────────────────────────────────────────
#  Protobuf 轻量解析 (无需编译 .proto)
# ────────────────────────────────────────────────────────────

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
    """VisualAnnotation → [{text, bbox, block_id, paragraph_id, content_type, confidence}, ...]"""
    lines = []
    for _, ld in _decode_msg(data).get(2, []):       # field 2 = repeated LineBox
        if not isinstance(ld, bytes):
            continue
        lf = _decode_msg(ld)

        # utf8_string (field 3)
        text = ""
        if 3 in lf and isinstance(lf[3][0][1], bytes):
            text = lf[3][0][1].decode("utf-8", "replace")

        # bounding_box (field 2) → Rect message
        bbox = {"x": 0, "y": 0, "w": 0, "h": 0}
        if 2 in lf and isinstance(lf[2][0][1], bytes):
            bbox = _parse_rect(lf[2][0][1])

        # block_id (field 5, varint)
        block_id = lf[5][0][1] if 5 in lf else -1
        # paragraph_id (field 11, varint)
        paragraph_id = lf[11][0][1] if 11 in lf else -1
        # content_type (field 8, varint): 0=PRINTED, 1=HANDWRITTEN, 6=FORMULA
        content_type = lf[8][0][1] if 8 in lf else 0
        # confidence (field 10, float)
        confidence = lf[10][0][1] if 10 in lf else 0.0

        lines.append({
            "text": text,
            "bbox": bbox,
            "block_id": block_id,
            "paragraph_id": paragraph_id,
            "content_type": content_type,
            "confidence": confidence,
        })
    return lines


# ────────────────────────────────────────────────────────────
#  排版感知 Markdown 格式化器
# ────────────────────────────────────────────────────────────

def _lines_to_markdown(lines: list[dict]) -> str:
    """将带布局信息的 OCR 行转换为排版感知的 Markdown。

    策略:
      - 根据 bbox 高度检测标题 (大字体 → # / ##)
      - 根据 block_id / paragraph_id 分段
      - 根据 x 坐标检测缩进
      - 根据列对齐检测表格结构
      - content_type=6 用 $ 包裹 (公式)
    """
    if not lines:
        return ""

    # 过滤空行
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return ""

    # ── 统计基准字高 ────────────────────────────────────────
    heights = [l["bbox"]["h"] for l in lines if l["bbox"]["h"] > 0]
    if not heights:
        return "\n".join(l["text"] for l in lines)

    median_h = sorted(heights)[len(heights) // 2]

    # ── 统计基准左边距 ─────────────────────────────────────
    x_vals = [l["bbox"]["x"] for l in lines if l["bbox"]["x"] > 0]
    base_x = min(x_vals) if x_vals else 0

    # ── 检测表格: 同一 y 范围内多个不重叠的文本块 ──────────
    table_rows = _detect_table(lines, median_h)

    # ── 逐行生成 Markdown ──────────────────────────────────
    parts: list[str] = []
    prev_block = -1
    prev_para = -1
    prev_y_bottom = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        # 跳过已被表格消费的行
        if table_rows and i in table_rows:
            row_indices = table_rows[i]
            table_lines_group = _build_table_block(lines, row_indices, table_rows)
            if table_lines_group:
                # 表格前空行
                if parts and parts[-1] != "":
                    parts.append("")
                parts.extend(table_lines_group)
                parts.append("")
                # 跳过所有被表格消费的行
                consumed = set()
                for ri in row_indices:
                    consumed.update(ri)
                i = max(consumed) + 1
                continue
            # fallthrough if table detection fails

        text = line["text"].strip()
        bbox = line["bbox"]
        h = bbox["h"]
        block_id = line["block_id"]
        para_id = line["paragraph_id"]
        ct = line["content_type"]

        # 段落/块间距检测
        y_gap = bbox["y"] - prev_y_bottom if prev_y_bottom > 0 else 0
        block_changed = (block_id != prev_block and prev_block != -1)
        para_changed = (para_id != prev_para and prev_para != -1)

        # 块切换 → 空行分隔
        if block_changed and parts and parts[-1] != "":
            parts.append("")
        elif para_changed and not block_changed:
            # 段落切换但同一块 → 空行
            if parts and parts[-1] != "":
                parts.append("")
        elif y_gap > median_h * 1.5 and parts and parts[-1] != "":
            # 大间距也加空行
            parts.append("")

        # 公式处理
        if ct == 6:
            parts.append(f"$$\n{text}\n$$")
            prev_y_bottom = bbox["y"] + h
            prev_block = block_id
            prev_para = para_id
            i += 1
            continue

        # 标题检测: 字高显著大于中位数
        if h > 0 and median_h > 0:
            ratio = h / median_h
            if ratio >= 2.0:
                parts.append(f"# {text}")
            elif ratio >= 1.5:
                parts.append(f"## {text}")
            elif ratio >= 1.25:
                parts.append(f"### {text}")
            else:
                # 缩进检测
                indent = bbox["x"] - base_x
                if indent > median_h * 2:
                    parts.append(f"  {text}")
                else:
                    parts.append(text)
        else:
            parts.append(text)

        prev_y_bottom = bbox["y"] + h
        prev_block = block_id
        prev_para = para_id
        i += 1

    # 清理多余空行
    result = "\n".join(parts)
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result.strip()


def _detect_table(lines: list[dict], median_h: float) -> dict[int, list[list[int]]]:
    """检测表格区域。返回 {起始行索引: [[row1_indices], [row2_indices], ...]}"""
    if len(lines) < 3:
        return {}

    # 按 y 坐标分组到行 (y 差距小于 median_h 的归为同一行)
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

    # 找出连续的多列行 (>=2列 且连续 >=3行 → 表格)
    multi_col_rows = []
    for row in rows:
        if len(row) >= 2:
            multi_col_rows.append(row)
        else:
            # 断开: 检查之前积累的是否够格
            if len(multi_col_rows) >= 3:
                start_idx = multi_col_rows[0][0]
                return {start_idx: multi_col_rows}
            multi_col_rows = []

    if len(multi_col_rows) >= 3:
        start_idx = multi_col_rows[0][0]
        return {start_idx: multi_col_rows}

    return {}


def _build_table_block(
    lines: list[dict], row_indices: list[list[int]], table_rows: dict
) -> list[str]:
    """将表格行转换为 Markdown 表格。"""
    if not row_indices:
        return []

    # 确定列数 (取最大列数)
    max_cols = max(len(row) for row in row_indices)
    if max_cols < 2:
        return []

    md_lines = []
    for ri, row in enumerate(row_indices):
        # 按 x 坐标排序
        sorted_cells = sorted(row, key=lambda idx: lines[idx]["bbox"]["x"])
        cells = [lines[idx]["text"].strip() for idx in sorted_cells]

        # 补齐列数
        while len(cells) < max_cols:
            cells.append("")

        md_lines.append("| " + " | ".join(cells) + " |")

        # 第一行后加分隔线
        if ri == 0:
            md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")

    return md_lines


# ────────────────────────────────────────────────────────────
#  Chrome Screen AI DLL 封装
# ────────────────────────────────────────────────────────────

_CB_SIZE = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_char_p)
_CB_CONTENT = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p)


class ChromeScreenAI:
    """Chrome Screen AI DLL 单例封装。模型只加载一次。"""

    _kBGRA_8888 = 6
    _kPremul = 2

    def __init__(self, dll_path: Optional[str] = None):
        self._dll = None
        self._ready = False
        self._max_dim = 0
        self._refs: list = []  # prevent GC of ctypes callbacks / buffers

        dll_path = dll_path or self._find_dll()
        if not dll_path:
            logger.warning("chrome_screen_ai.dll not found — is Chrome installed?")
            return

        dll_dir = str(Path(dll_path).parent)
        try:
            dll = ctypes.CDLL(dll_path)
            self._setup(dll, dll_dir)
        except Exception as e:
            logger.error(f"Screen AI init failed: {e}")

    # ── locate DLL ──────────────────────────────────────────

    @staticmethod
    def _find_dll() -> Optional[str]:
        pattern = os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\*\chrome_screen_ai.dll"
        )
        hits = sorted(glob(pattern), reverse=True)
        return hits[0] if hits else None

    # ── DLL init ────────────────────────────────────────────

    def _setup(self, dll, dll_dir: str):
        # file-content callbacks (model loading)
        def _size(p):
            try:
                fp = os.path.join(dll_dir, p.decode())
                return os.path.getsize(fp) if os.path.exists(fp) else 0
            except Exception:
                return 0

        def _read(p, sz, buf):
            try:
                with open(os.path.join(dll_dir, p.decode()), "rb") as f:
                    ctypes.memmove(buf, f.read(sz), sz)
            except Exception:
                pass

        cb_s, cb_r = _CB_SIZE(_size), _CB_CONTENT(_read)
        self._refs.extend([cb_s, cb_r])
        dll.SetFileContentFunctions(cb_s, cb_r)

        # init OCR engine
        dll.InitOCRUsingCallback.argtypes = []
        dll.InitOCRUsingCallback.restype = ctypes.c_bool
        if not dll.InitOCRUsingCallback():
            logger.error("InitOCRUsingCallback → False")
            return

        dll.GetMaxImageDimension.argtypes = []
        dll.GetMaxImageDimension.restype = ctypes.c_uint32
        self._max_dim = dll.GetMaxImageDimension()

        dll.PerformOCR.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        dll.PerformOCR.restype = ctypes.c_void_p
        dll.FreeLibraryAllocatedCharArray.argtypes = [ctypes.c_void_p]
        dll.FreeLibraryAllocatedCharArray.restype = None

        # version
        dll.GetLibraryVersion.argtypes = [ctypes.POINTER(ctypes.c_uint32)] * 2
        dll.GetLibraryVersion.restype = None
        ma, mi = ctypes.c_uint32(), ctypes.c_uint32()
        dll.GetLibraryVersion(ctypes.byref(ma), ctypes.byref(mi))

        self._dll = dll
        self._ready = True
        logger.info(f"Screen AI v{ma.value}.{mi.value} ready (max {self._max_dim}px)")

    # ── public API ──────────────────────────────────────────

    @property
    def ok(self) -> bool:
        return self._ready

    @property
    def max_dimension(self) -> int:
        return self._max_dim

    def _prepare_image(self, image):
        """将任意图像输入转换为 (bgra_array, w, h)。"""
        from PIL import Image as PILImage

        if isinstance(image, (str, Path)):
            image = PILImage.open(str(image))
        elif isinstance(image, np.ndarray):
            image = PILImage.fromarray(image)

        image = image.convert("RGB")
        w, h = image.size

        # 超出最大尺寸时等比缩放
        if self._max_dim and max(w, h) > self._max_dim:
            r = self._max_dim / max(w, h)
            w, h = int(w * r), int(h * r)
            image = image.resize((w, h), PILImage.LANCZOS)

        # RGB → BGRA (Skia native on Windows)
        rgb = np.asarray(image)
        bgra = np.empty((h, w, 4), np.uint8)
        bgra[..., 0] = rgb[..., 2]
        bgra[..., 1] = rgb[..., 1]
        bgra[..., 2] = rgb[..., 0]
        bgra[..., 3] = 255
        bgra = np.ascontiguousarray(bgra)
        return bgra, w, h

    def ocr(self, image) -> str:
        """OCR 任意图像，返回纯文本 (无排版)。"""
        if not self._ready:
            raise RuntimeError("Screen AI engine not ready")
        bgra, w, h = self._prepare_image(image)
        proto = self._call_dll_raw(bgra, w, h)
        if not proto:
            return ""
        lines = _parse_visual_annotation(proto)
        return "\n".join(l["text"] for l in lines if l["text"].strip())

    def ocr_markdown(self, image) -> str:
        """OCR 任意图像，返回排版感知的 Markdown。"""
        if not self._ready:
            raise RuntimeError("Screen AI engine not ready")
        bgra, w, h = self._prepare_image(image)
        proto = self._call_dll_raw(bgra, w, h)
        if not proto:
            return ""
        lines = _parse_visual_annotation(proto)
        return _lines_to_markdown(lines)

    # ── low-level DLL call ──────────────────────────────────

    def _call_dll_raw(self, bgra: np.ndarray, w: int, h: int) -> bytes:
        """调用 PerformOCR，返回原始 protobuf 字节。"""
        row_bytes = w * 4
        pix_buf = (ctypes.c_uint8 * bgra.nbytes).from_buffer(bgra)
        pix_ptr = ctypes.cast(pix_buf, ctypes.c_void_p).value

        # SkPixelRef (fake — 只需非 NULL 以通过 isNull() 检查)
        pr = bytearray(48)
        struct.pack_into("<Qi", pr, 0, 0, 999999)          # vtable=0, refCnt
        struct.pack_into("<iiQQ", pr, 16, w, h, pix_ptr, row_bytes)
        pr_buf = (ctypes.c_uint8 * 48)(*pr)
        self._refs.append(pr_buf)  # prevent GC during call

        # SkBitmap (48 bytes, layout reversed-engineered from Chromium/Skia)
        bm = bytearray(48)
        struct.pack_into("<QQQ", bm, 0,
                         ctypes.cast(pr_buf, ctypes.c_void_p).value,
                         pix_ptr, row_bytes)
        struct.pack_into("<Qii", bm, 24, 0, self._kBGRA_8888, self._kPremul)
        struct.pack_into("<ii", bm, 40, w, h)
        bm_buf = (ctypes.c_uint8 * 48)(*bm)

        alen = ctypes.c_uint32(0)
        rp = self._dll.PerformOCR(ctypes.cast(bm_buf, ctypes.c_void_p),
                                  ctypes.byref(alen))
        if not rp or not alen.value:
            return b""

        proto = bytes((ctypes.c_char * alen.value).from_address(rp))
        self._dll.FreeLibraryAllocatedCharArray(rp)
        return proto


# ────────────────────────────────────────────────────────────
#  全局单例 (模型只加载一次，后续调用零开销)
# ────────────────────────────────────────────────────────────

_engine: Optional[ChromeScreenAI] = None


def _get_engine() -> ChromeScreenAI:
    global _engine
    if _engine is None:
        _engine = ChromeScreenAI()
    if not _engine.ok:
        raise RuntimeError(
            "Chrome Screen AI 不可用。请确认已安装 Google Chrome 且 screen_ai 组件已下载。"
        )
    return _engine


# ────────────────────────────────────────────────────────────
#  顶层 API — 用户只需要这两个函数
# ────────────────────────────────────────────────────────────

def image_to_text(image, *, engine: Optional[ChromeScreenAI] = None) -> str:
    """图片 → 排版感知的 Markdown 文本。

    >>> text = image_to_text("photo.png")
    >>> text = image_to_text(pil_image)
    >>> text = image_to_text(numpy_rgb_array)
    """
    return (engine or _get_engine()).ocr_markdown(image)


def pdf_to_markdown(
    pdf_path: str,
    *,
    dpi: int = 200,
    pages: Optional[Union[int, list[int], range]] = None,
    engine: Optional[ChromeScreenAI] = None,
) -> str:
    """PDF → 排版感知的 Markdown 文本。

    Args:
        pdf_path:  PDF 文件路径
        dpi:       渲染 DPI (越高越清晰，但越慢)
        pages:     指定页码 (从1开始)。None=全部, int=单页, list/range=多页

    Returns:
        Markdown 格式的全文 (含标题层级、段落、表格)

    >>> md = pdf_to_markdown("scan.pdf")
    >>> md = pdf_to_markdown("scan.pdf", pages=range(1, 11))   # 前10页
    >>> md = pdf_to_markdown("scan.pdf", pages=[1, 3, 5])      # 指定页
    """
    import fitz

    ai = engine or _get_engine()
    doc = fitz.open(pdf_path)
    total = len(doc)

    # 规范化页码列表 (外部 1-based → 内部 0-based)
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
        page = doc[idx]

        # 1) 先尝试直接提取文本 (文本型 PDF，瞬间完成)
        raw_text = page.get_text().strip()

        # 2) 文本不足 → OCR (排版感知)
        if len(raw_text) <= 50:
            scale = min(dpi / 72, max_dim / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            from PIL import Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = ai.ocr_markdown(img)
        else:
            text = raw_text

        parts.append(f"## Page {idx + 1}\n\n{text}")

        if (len(parts)) % 20 == 0:
            logger.info(f"  {len(parts)}/{len(indices)} pages done")

    doc.close()

    header = f"# {Path(pdf_path).stem}\n\n"
    return header + "\n\n---\n\n".join(parts) + "\n"
