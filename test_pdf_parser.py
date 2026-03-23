"""
PDF Parser 测试脚本

用于测试 screen_ai_pdf_parser 的功能。

Usage:
    python test_pdf_parser.py [pdf_file_path]
"""

import os
import sys
from pathlib import Path

# 修复 Windows 编码问题
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加父目录到路径以导入模块
sys.path.insert(0, str(Path(__file__).parent))

from screen_ai_pdf_parser import (
    PDFParser,
    ExtractMode,
    ChromeScreenAI,
    parse_pdf
)


def print_section(title: str):
    """打印分隔标题"""
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print('=' * 50)


def test_dependencies():
    """测试依赖库"""
    print_section("测试依赖库")

    # 测试 PyMuPDF
    try:
        import fitz
        print(f"✓ PyMuPDF (fitz) 已安装 - 版本: {fitz.version}")
        return True
    except ImportError:
        print("✗ PyMuPDF 未安装")
        print("  安装命令: pip install pymupdf")
        return False


def test_screen_ai():
    """测试 Chrome Screen AI"""
    print_section("测试 Chrome Screen AI")

    screen_ai = ChromeScreenAI()

    if screen_ai.is_available():
        version = screen_ai.get_version()
        print(f"✓ Chrome Screen AI DLL 已加载")
        print(f"  版本: {version}")
        print(f"  注意: OCR 功能实现中...")
        return True
    else:
        print("ℹ Chrome Screen AI DLL 不可用")
        print("  将使用 PyMuPDF 的内置文本提取")
        return False


def test_parser_creation():
    """测试解析器创建"""
    print_section("测试解析器创建")

    # 测试不同模式的解析器
    modes = [
        (ExtractMode.DIRECT, "直接文本提取模式"),
        (ExtractMode.OCR, "OCR 模式"),
        (ExtractMode.AUTO, "自动检测模式")
    ]

    for mode, desc in modes:
        try:
            parser = PDFParser(extract_mode=mode)
            status = "✓" if parser.available else "✗"
            print(f"{status} {desc}: {'可用' if parser.available else '不可用'}")
        except Exception as e:
            print(f"✗ {mode}: 错误 - {e}")

    # 测试带 Screen AI 的解析器
    try:
        parser = PDFParser(use_screen_ai=True)
        if parser.screen_ai and parser.screen_ai.is_available():
            print("✓ 带 Chrome Screen AI 的解析器: 可用")
        else:
            print("ℹ 带 Chrome Screen AI 的解析器: DLL 不可用，将使用回退方案")
    except Exception as e:
        print(f"✗ 带 Chrome Screen AI 的解析器: 错误 - {e}")


def create_demo_pdf(path: str = "demo_test.pdf"):
    """创建演示 PDF 文件"""
    print(f"\n创建演示 PDF: {path}")

    try:
        import fitz

        doc = fitz.open()

        # 添加第一页（文本内容）
        page = doc.new_page()
        page.insert_text(
            (50, 50),
            "PDF 解析器测试文档\n\n"
            "这是一个用于测试 PDF 解析功能的演示文档。\n\n"
            "主要功能：\n"
            "1. 直接文本提取\n"
            "2. OCR 图像识别\n"
            "3. 自动模式检测\n\n"
            "测试日期: 2025-02-15\n"
            "作者: PDF Parser Test Suite",
            fontsize=12,
            fontname="helvetica"
        )

        # 添加第二页（更多文本）
        page = doc.new_page()
        page.insert_text(
            (50, 50),
            "第二页测试内容\n\n"
            "PDF Parser 支持多种文本提取模式。\n\n"
            "自动模式 (AUTO) 会智能选择最佳提取方式：\n"
            "- 如果页面包含足够文本，使用直接提取\n"
            "- 如果文本太少，可能是扫描版，使用 OCR\n\n"
            "这使得解析器能够高效处理各种类型的 PDF。",
            fontsize=12,
            fontname="helvetica"
        )

        doc.save(path)
        doc.close()

        print(f"✓ 演示 PDF 创建成功: {path}")
        return path

    except Exception as e:
        print(f"✗ 创建演示 PDF 失败: {e}")
        return None


def test_parse_pdf(pdf_path: str):
    """测试 PDF 解析"""
    print_section(f"测试 PDF 解析: {pdf_path}")

    if not os.path.exists(pdf_path):
        print(f"✗ 文件不存在: {pdf_path}")
        return

    # 测试自动模式
    print("\n--- 自动模式 ---")
    parser = PDFParser(extract_mode=ExtractMode.AUTO)

    try:
        result = parser.parse(pdf_path)

        print(f"✓ 解析成功")
        print(f"  总页数: {result.total_pages}")
        print(f"  总字符数: {result.total_chars}")
        print(f"  模式分布:")
        for mode, count in result.mode_distribution.items():
            if count > 0:
                print(f"    - {mode}: {count} 页")

        # 显示元数据
        if result.metadata:
            print(f"\n  元数据:")
            for key, value in result.metadata.items():
                if key not in ['page_count', 'is_encrypted', 'is_pdf'] and value:
                    print(f"    {key}: {value}")

        # 显示第一页内容预览
        if result.pages:
            first_page = result.pages[0]
            print(f"\n  第 1 页预览 (前 200 字符):")
            preview = first_page.text[:200] + "..." if len(first_page.text) > 200 else first_page.text
            for line in preview.split('\n')[:5]:
                print(f"    {line}")

        return result

    except Exception as e:
        print(f"✗ 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_export(result, output_dir: str = "test_output"):
    """测试导出功能"""
    print_section("测试导出功能")

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    print(f"输出目录: {output_dir}")

    parser = PDFParser()

    formats = [("txt", "文本文件"), ("md", "Markdown 文件"), ("json", "JSON 文件")]

    for fmt, desc in formats:
        output_path = os.path.join(output_dir, f"output.{fmt}")
        try:
            parser.export_to_file(result, output_path, fmt)
            print(f"✓ 导出 {desc}: {output_path}")

            # 显示文件大小
            size = os.path.getsize(output_path)
            print(f"  文件大小: {size:,} 字节")

        except Exception as e:
            print(f"✗ 导出 {desc} 失败: {e}")


def test_convenience_function(pdf_path: str):
    """测试便捷函数"""
    print_section("测试便捷函数")

    output_path = "test_output/quick_output.txt"

    try:
        result = parse_pdf(
            pdf_path,
            mode=ExtractMode.AUTO,
            use_screen_ai=False,
            output_path=output_path
        )

        if result:
            print(f"✓ 便捷函数执行成功")
            print(f"  输出文件: {output_path}")
            return True
        else:
            print(f"✗ 便捷函数执行失败")
            return False

    except Exception as e:
        print(f"✗ 便捷函数错误: {e}")
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 50)
    print("  PDF Parser 功能测试")
    print("=" * 50)

    # 1. 测试依赖
    if not test_dependencies():
        print("\n缺少必要依赖，请安装 PyMuPDF")
        return

    # 2. 测试 Screen AI
    test_screen_ai()

    # 3. 测试解析器创建
    test_parser_creation()

    # 4. 确定测试 PDF
    pdf_path = None

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        if not os.path.exists(pdf_path):
            print(f"\n✗ 指定的 PDF 文件不存在: {pdf_path}")
            pdf_path = None

    if pdf_path is None:
        print("\n未指定 PDF 文件，创建演示文档...")
        pdf_path = create_demo_pdf()

    if not pdf_path:
        print("\n✗ 无可用的 PDF 文件进行测试")
        return

    # 5. 测试 PDF 解析
    result = test_parse_pdf(pdf_path)

    if not result:
        return

    # 6. 测试导出功能
    test_export(result)

    # 7. 测试便捷函数
    test_convenience_function(pdf_path)

    # 完成
    print_section("测试完成")
    print("✓ 所有基础功能测试完成")
    print(f"\n测试文件位置: test_output/")
    print(f"演示 PDF: {pdf_path}")


if __name__ == "__main__":
    main()
