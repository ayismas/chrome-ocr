"""Command-line interface for chrome-ocr."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, ocr_img, ocr_pdf
from .chrome_ocr import ScreenAIEngine


def parse_pages_spec(spec: str) -> list[int]:
    """Parse a 1-based page selection string such as ``1,3,5-7``."""
    spec = spec.strip()
    if not spec:
        raise argparse.ArgumentTypeError("Page spec must not be empty")

    pages: list[int] = []
    seen: set[int] = set()

    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise argparse.ArgumentTypeError(f"Invalid page spec: {spec!r}")

        if "-" in token:
            start_str, end_str = token.split("-", 1)
            try:
                start = int(start_str)
                end = int(end_str)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(f"Invalid page range: {token!r}") from exc
            if start <= 0 or end <= 0 or end < start:
                raise argparse.ArgumentTypeError(f"Invalid page range: {token!r}")
            values = range(start, end + 1)
        else:
            try:
                page = int(token)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(f"Invalid page number: {token!r}") from exc
            if page <= 0:
                raise argparse.ArgumentTypeError(f"Invalid page number: {token!r}")
            values = [page]

        for value in values:
            if value not in seen:
                seen.add(value)
                pages.append(value)

    return pages


def _write_result(text: str, output_path: str | None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")


def _run_img(args: argparse.Namespace) -> int:
    text = ocr_img(args.input)
    _write_result(text, args.output)
    return 0


def _run_pdf(args: argparse.Namespace) -> int:
    pages = parse_pages_spec(args.pages) if args.pages else None
    text = ocr_pdf(
        args.input,
        dpi=args.dpi,
        pages=pages,
        page_sep=args.page_sep,
    )
    _write_result(text, args.output)
    return 0


def _run_doctor(args: argparse.Namespace) -> int:  # noqa: ARG001
    dll_path = ScreenAIEngine._find_dll()
    if not dll_path:
        print("status: missing")
        print("dll: not found")
        print("hint: enable a Chrome accessibility feature so the Screen AI component downloads")
        return 1

    engine = ScreenAIEngine(dll_path=dll_path)
    print(f"status: {'ready' if engine.ok else 'found-but-not-ready'}")
    print(f"dll: {dll_path}")
    if engine.ok:
        print(f"max_image_dimension: {engine.max_dimension}")
        return 0
    print("hint: the DLL exists, but initialisation failed in this Python process")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chrome-ocr",
        description="Turn local PDFs and images into layout-aware Markdown with Chrome's Screen AI engine.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Python logging level for library diagnostics.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    img_parser = subparsers.add_parser(
        "img",
        help="OCR an image and emit Markdown.",
    )
    img_parser.add_argument("input", help="Path to the image file.")
    img_parser.add_argument(
        "-o",
        "--output",
        help="Write Markdown to a file instead of stdout.",
    )
    img_parser.set_defaults(handler=_run_img)

    pdf_parser = subparsers.add_parser(
        "pdf",
        help="Extract or OCR a PDF and emit Markdown.",
    )
    pdf_parser.add_argument("input", help="Path to the PDF file.")
    pdf_parser.add_argument(
        "-o",
        "--output",
        help="Write Markdown to a file instead of stdout.",
    )
    pdf_parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Rasterisation DPI for scanned pages. Default: 200.",
    )
    pdf_parser.add_argument(
        "--pages",
        help="1-based page spec such as '1,3,5-8'. Defaults to all pages.",
    )
    pdf_parser.add_argument(
        "--page-sep",
        default="\n\n",
        help="String inserted between extracted pages. Default: blank line.",
    )
    pdf_parser.set_defaults(handler=_run_pdf)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check whether Chrome's Screen AI DLL is installed and initialises correctly.",
    )
    doctor_parser.set_defaults(handler=_run_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
