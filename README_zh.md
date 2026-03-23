# chrome-ocr

[![Tests](https://github.com/ayismas/chrome-ocr/actions/workflows/test.yml/badge.svg)](https://github.com/ayismas/chrome-ocr/actions/workflows/test.yml)

利用 Chrome 隐藏的 OCR 引擎，把本地 PDF 和图片转换成 Markdown。

无需 API Key，无需云端调用，无需额外下载模型。Chrome 已经自带模型，这个项目直接调用它。

## 为什么这个项目有意思

- 它复用 Chrome 内置的 Screen AI 组件，而不是再打包一套新的 OCR 模型。
- 它完全本地运行，处理文档时不需要把内容发到云端。
- 它输出的是带版面结构的 Markdown，而不只是纯文本。
- 它会优先走文本层 PDF 的快速路径，只有真正需要时才做 OCR。

## 快速演示

当前项目以源码安装为主。

```bash
git clone https://github.com/ayismas/chrome-ocr.git
cd chrome-ocr
pip install -e .[pdf]
```

先检查 Chrome OCR 组件是否可用：

```bash
chrome-ocr doctor
python -m chrome_ocr doctor
```

把 PDF 提取成 Markdown：

```bash
chrome-ocr pdf report.pdf -o report.md
chrome-ocr pdf report.pdf --pages 1,3,5-8 --dpi 300
```

识别图片：

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

也支持底层引擎复用：

```python
from chrome_ocr import ScreenAIEngine, ocr_pdf

engine = ScreenAIEngine()
markdown = ocr_pdf("report.pdf", engine=engine)
```

## 你能得到什么

- **PDF 转 Markdown**：文本型 PDF 直接提取，扫描页自动 OCR。
- **图片转 Markdown**：支持文件路径、`PIL.Image` 和 NumPy 数组。
- **排版感知输出**：会根据几何信息重建标题、段落、缩进、表格和公式。
- **热启动开销低**：DLL 在进程内只加载一次，后续调用会复用。

## CLI 说明

### `chrome-ocr doctor`

检查 Chrome 的 `chrome_screen_ai.dll` 是否存在，以及是否能正确初始化。

### `chrome-ocr img INPUT [-o OUTPUT]`

识别图片并输出 Markdown；默认写到标准输出，使用 `-o` 可写入文件。

### `chrome-ocr pdf INPUT [-o OUTPUT] [--dpi 200] [--pages 1,3,5-8]`

提取或 OCR 一个 PDF，并输出 Markdown。

- `--pages` 使用从 1 开始的页码。
- `--page-sep` 控制多页内容之间如何拼接。
- `--dpi` 影响扫描页光栅化质量。

## API 参考

### `ocr_pdf(pdf_path, *, dpi=200, pages=None, page_sep="\n\n", engine=None) -> str`

只返回 PDF 本身的内容，不会额外注入文件标题或页眉。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `pdf_path` | `str` | — | PDF 文件路径 |
| `dpi` | `int` | `200` | 扫描页光栅化 DPI |
| `pages` | `int \| list[int] \| range \| None` | `None` | 从 1 开始的页码选择 |
| `page_sep` | `str` | `"\n\n"` | 多页之间的分隔符 |
| `engine` | `ScreenAIEngine \| None` | `None` | 可选的复用引擎 |

### `ocr_img(image, *, engine=None) -> str`

把图片识别为带排版结构的 Markdown 文本。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `image` | `str \| Path \| PIL.Image \| np.ndarray` | 图片输入 |
| `engine` | `ScreenAIEngine \| None` | 可选的复用引擎 |

`ocr_img_md` 是完全相同的别名。

### `ScreenAIEngine(dll_path=None)`

高级接口，适用于自定义 DLL 路径或跨调用复用引擎。

## 自己跑 Benchmark

仓库里自带了可复现的 benchmark harness，你可以在自己的机器上直接生成数据，而不是只看截图。

```bash
python benchmarks/run_benchmark.py img path/to/scan.png --repeat 5
python benchmarks/run_benchmark.py pdf path/to/report.pdf --repeat 3 --pages 1-5
```

具体方法和外部工具对比方式见 [benchmarks/README.md](benchmarks/README.md)。

## 环境要求

| 要求 | 说明 |
| --- | --- |
| Windows 10 / 11 | `chrome_screen_ai.dll` 仅支持 Windows |
| Google Chrome | 图片 OCR 和扫描版 / 图片型 PDF 需要 |
| Python >= 3.9 | 已在测试矩阵中覆盖 |

> `ocr_pdf()` 仍然可以在没有 Chrome Screen AI 的情况下直接提取文本层 PDF。只有页面几乎没有内嵌文本时，才需要 DLL 来执行 OCR。

## 如何确认 Screen AI 组件存在

打开 Chrome，进入 设置 -> 无障碍，启用任意与屏幕阅读相关的功能，然后确认下面这个目录存在：

```text
%LOCALAPPDATA%\Google\Chrome\User Data\screen_ai\
```

## 输出格式

Markdown 格式化器会按如下方式映射视觉结构：

| 视觉元素 | Markdown 输出 |
| --- | --- |
| 大字体（>= 正文 2 倍） | `# Heading` |
| 中字体（1.5-2 倍） | `## Heading` |
| 稍大字体（1.25-1.5 倍） | `### Heading` |
| 缩进文本 | 前导空格 |
| 多列行（>= 3 行） | GFM 表格 |
| 公式（`content_type=6`） | `$$...$$` 块 |

## 工作原理

Chrome 附带了一个无障碍组件 `chrome_screen_ai.dll`。

这个库通过 `ctypes` 加载 DLL，使用从 Chromium 和 Skia 源码逆向得到的 `SkBitmap` 内存布局喂入图像数据，并在不编译任何 `.proto` 文件的前提下解析返回的 `VisualAnnotation` protobuf。

随后再利用边界框元数据重建文档结构，而这部分信息通常会被普通 OCR 封装层丢掉。

## 项目附加内容

- [benchmarks/README.md](benchmarks/README.md)：可复现 benchmark 流程
- [docs/launch-kit.md](docs/launch-kit.md)：维护者发布文案和发帖模板
- [screen_ai_pdf_parser.py](screen_ai_pdf_parser.py)：兼容旧导入方式的包装层

## 运行测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

依赖 Chrome DLL 的测试会在组件未安装时自动跳过。

## 许可证

MIT，详见 [LICENSE](LICENSE)。

`chrome_screen_ai.dll` 仍然属于 Google Chrome 的组成部分，并受 Google 条款约束。本项目不会分发或修改该 DLL。
