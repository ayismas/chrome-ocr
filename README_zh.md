# chrome-ocr

基于 Chrome 内置 Screen AI 引擎的本地离线 OCR Python 库。

无需 API Key，无需联网，无需单独下载模型。
Chrome 已自带该模型，本库直接调用即可。

## 功能特点

- **PDF 转 Markdown** — 文本型 PDF 直接提取，扫描版 / 图片型 PDF 自动 OCR
- **图片转文本** — 支持文件路径、`PIL.Image`、NumPy 数组三种输入
- **排版感知输出** — 依据边界框几何信息还原标题层级、段落、多列表格和数学公式（`$$...$$`）
- **零额外体积** — 复用 Chrome 生产级 ML 模型（约 30 MB，已在本机磁盘）
- **全局单例引擎** — DLL 只加载一次，后续调用开销可忽略不计

## 环境要求

| 要求 | 说明 |
|---|---|
| Windows 10 / 11 | `chrome_screen_ai.dll` 仅支持 Windows |
| Google Chrome | Screen AI 组件由 Chrome 为无障碍功能自动下载 |
| Python ≥ 3.9 | |

```bash
pip install pymupdf pillow numpy protobuf
```

> **确认 Screen AI 组件已就绪**
> 打开 Chrome → 设置 → 无障碍 → 启用任意屏幕阅读功能，
> 然后确认 `%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\` 目录存在。

## 快速上手

```python
from chrome_ocr import ocr_pdf, ocr_img

# PDF（文本型或扫描版）→ Markdown
md = ocr_pdf("report.pdf")

# 图片文件 → Markdown
text = ocr_img("scan.png")

# 也支持 PIL Image 或 NumPy 数组
from PIL import Image
text = ocr_img(Image.open("scan.png"))

import numpy as np
text = ocr_img(np.array(Image.open("scan.png")))
```

## API 参考

### `ocr_pdf(pdf_path, *, dpi=200, pages=None, page_sep="\n\n", engine=None) -> str`

将 PDF 转换为排版感知的 Markdown。
仅返回 PDF 本身的内容，不插入文件名标题或 `## Page N` 等标记。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `pdf_path` | `str` | — | PDF 文件路径 |
| `dpi` | `int` | `200` | 扫描页光栅化分辨率，越高越清晰，耗时越长 |
| `pages` | `int \| list[int] \| range \| None` | `None` | 从 1 开始的页码；`None` 处理全部页面 |
| `page_sep` | `str` | `"\n\n"` | 多页之间的分隔符；`""` 则直接拼接 |
| `engine` | `ScreenAIEngine \| None` | `None` | 复用已有引擎实例；`None` 时使用模块级单例 |

**返回值** — `str`：仅包含 PDF 原文内容的 Markdown 字符串。

```python
md = ocr_pdf("report.pdf")                             # 全部页面
md = ocr_pdf("report.pdf", pages=1)                    # 第 1 页
md = ocr_pdf("report.pdf", pages=[1, 3, 5])            # 指定页面
md = ocr_pdf("report.pdf", pages=range(1, 11))         # 前 10 页
md = ocr_pdf("report.pdf", dpi=300)                    # 更高精度
md = ocr_pdf("report.pdf", page_sep="\n\n---\n\n")     # 页间加分隔线
```

---

### `ocr_img(image, *, engine=None) -> str`

将图片转换为排版感知的 Markdown 文本。

| 参数 | 类型 | 说明 |
|---|---|---|
| `image` | `str \| Path \| PIL.Image \| np.ndarray` | 图片来源 |
| `engine` | `ScreenAIEngine \| None` | 可选引擎实例 |

`ocr_img_md` 是完全相同的别名。

```python
text = ocr_img("photo.png")
text = ocr_img(pil_image)
text = ocr_img(numpy_rgb_array)
```

---

### `ScreenAIEngine(dll_path=None)`

底层引擎类，适用于需要自定义 DLL 路径或跨调用复用引擎的高级场景。

```python
from chrome_ocr import ScreenAIEngine

engine = ScreenAIEngine()           # 自动定位 DLL
if engine.ok:
    print(engine.max_dimension)     # 引擎支持的最大图像边长（像素）
    text = engine.ocr("page.png")           # 纯文本
    md   = engine.ocr_markdown("page.png")  # 排版感知 Markdown

# 跨多个文件复用同一引擎
md = ocr_pdf("a.pdf", engine=engine)
md = ocr_pdf("b.pdf", engine=engine)
```

## 输出格式说明

两个函数均返回 Markdown 字符串，视觉排版元素的映射规则如下：

| 视觉元素 | Markdown 输出 |
|---|---|
| 大字体（≥ 正文 2 倍） | `# 标题` |
| 中字体（1.5–2 倍） | `## 标题` |
| 较大字体（1.25–1.5 倍） | `### 标题` |
| 缩进文本 | 前导空格 |
| 多列行（≥ 3 行） | GFM 表格 |
| 公式（`content_type=6`） | `$$...$$` 块 |
| 页面分隔（仅 PDF） | `## Page N` + `---` |

## 项目结构

```
chrome_ocr/
├── chrome_ocr.py          # 核心引擎 + 公开 API
├── __init__.py            # 包入口
├── example/
│   ├── demo.ipynb         # 交互式使用示例
│   └── paper.pdf          # 示例 PDF（请替换为自己的文件）
└── tests/
    └── test_chrome_ocr.py # pytest 测试套件
```

## 工作原理

Chrome 随无障碍功能附带了一个名为 **Screen AI** 的组件（`chrome_screen_ai.dll`）。
本库通过 `ctypes` 加载该 DLL，利用从 Chromium/Skia 源码逆向得到的 `SkBitmap` 内存布局
向其提交图像数据，并在不编译任何 `.proto` 文件的前提下解析返回的 protobuf（`VisualAnnotation`）。

响应中的边界框元数据用于还原文档结构（标题、段落、表格），这是普通 OCR 工具通常会丢弃的信息。

## 运行测试

```bash
pip install pytest pymupdf pillow numpy protobuf
pytest tests/test_chrome_ocr.py -v
```

未安装 Chrome 时，依赖 DLL 的测试会自动跳过。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

> **说明：** `chrome_screen_ai.dll` 是 Google Chrome 的组成部分，受 Google 服务条款约束。
> 本项目仅加载 Chrome 已安装在本机的 DLL，不分发也不修改该 DLL。
