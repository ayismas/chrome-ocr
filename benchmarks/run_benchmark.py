"""
Reproducible benchmark harness for chrome-ocr.

Examples
--------
    python benchmarks/run_benchmark.py img scan.png --repeat 5
    python benchmarks/run_benchmark.py pdf report.pdf --repeat 3 --pages 1-5
    python benchmarks/run_benchmark.py img scan.png \
        --compare "tesseract=tesseract {input} stdout"
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chrome_ocr import ocr_img, ocr_pdf
from chrome_ocr.cli import parse_pages_spec


@dataclass
class BenchmarkSummary:
    label: str
    runs: list[float]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.runs)

    @property
    def median(self) -> float:
        return statistics.median(self.runs)

    @property
    def minimum(self) -> float:
        return min(self.runs)

    @property
    def maximum(self) -> float:
        return max(self.runs)


def _time_call(fn, *, repeat: int, warmup: int) -> list[float]:
    for _ in range(warmup):
        fn()

    runs: list[float] = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - start)
    return runs


def _parse_compare_spec(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            "Compare specs must use the form 'label=command {input}'"
        )
    label, command = spec.split("=", 1)
    label = label.strip()
    command = command.strip()
    if not label or not command:
        raise argparse.ArgumentTypeError(
            "Compare specs must use the form 'label=command {input}'"
        )
    return label, command


def _run_external_command(command_template: str, input_path: str) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = str(Path(temp_dir) / "result.txt")
        command = command_template.format(input=input_path, output=output_path)
        completed = subprocess.run(command, shell=True, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"Command failed with exit code {completed.returncode}: {command}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )


def _benchmark_chrome_ocr(args: argparse.Namespace) -> BenchmarkSummary:
    if args.kind == "img":
        def fn() -> str:
            return ocr_img(args.input)
    else:
        def fn() -> str:
            return ocr_pdf(
                args.input,
                dpi=args.dpi,
                pages=parse_pages_spec(args.pages) if args.pages else None,
                page_sep=args.page_sep,
            )
    runs = _time_call(fn, repeat=args.repeat, warmup=args.warmup)
    return BenchmarkSummary(label="chrome-ocr", runs=runs)


def _benchmark_external(args: argparse.Namespace, label: str, command: str) -> BenchmarkSummary:
    def fn() -> None:
        _run_external_command(command, args.input)

    runs = _time_call(fn, repeat=args.repeat, warmup=args.warmup)
    return BenchmarkSummary(label=label, runs=runs)


def _to_markdown(results: list[BenchmarkSummary]) -> str:
    lines = [
        "| Tool | Runs | Mean (s) | Median (s) | Min (s) | Max (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            "| {label} | {count} | {mean:.4f} | {median:.4f} | {minimum:.4f} | {maximum:.4f} |".format(
                label=result.label,
                count=len(result.runs),
                mean=result.mean,
                median=result.median,
                minimum=result.minimum,
                maximum=result.maximum,
            )
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark chrome-ocr and optional external OCR commands on the same input.",
    )
    parser.add_argument("kind", choices=["img", "pdf"], help="Benchmark image OCR or PDF OCR.")
    parser.add_argument("input", help="Path to the image or PDF file.")
    parser.add_argument("--repeat", type=int, default=5, help="Measured runs per tool. Default: 5.")
    parser.add_argument("--warmup", type=int, default=1, help="Warm-up runs per tool. Default: 1.")
    parser.add_argument("--dpi", type=int, default=200, help="PDF rasterisation DPI. Default: 200.")
    parser.add_argument("--pages", help="Optional PDF page spec such as '1,3,5-8'.")
    parser.add_argument(
        "--page-sep",
        default="\n\n",
        help="String inserted between PDF pages when benchmarking chrome-ocr.",
    )
    parser.add_argument(
        "--compare",
        action="append",
        default=[],
        metavar="LABEL=COMMAND",
        help="Optional external command, shell-executed with {input} and optional {output} placeholders.",
    )
    parser.add_argument(
        "--json-out",
        help="Write full benchmark data to a JSON file.",
    )
    parser.add_argument(
        "--markdown-out",
        help="Write the Markdown summary table to a file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    results = [_benchmark_chrome_ocr(args)]
    for spec in args.compare:
        label, command = _parse_compare_spec(spec)
        results.append(_benchmark_external(args, label, command))

    markdown = _to_markdown(results)
    payload = [asdict(result) for result in results]

    print(markdown)

    if args.markdown_out:
        path = Path(args.markdown_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown + "\n", encoding="utf-8")

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
