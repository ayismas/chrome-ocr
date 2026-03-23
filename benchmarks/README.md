# Benchmarks

This repository includes a small benchmark harness so you can generate claims that are reproducible on your own machine instead of relying on hand-wavy screenshots.

## What to measure

- `chrome-ocr` vs direct text extraction on text-layer PDFs
- `chrome-ocr` vs Tesseract on scanned PDFs
- `chrome-ocr` vs another OCR CLI on clean images
- cold-start vs warm-start timings

## Run the harness

From the repository root:

```bash
python benchmarks/run_benchmark.py img path/to/scan.png --repeat 5
python benchmarks/run_benchmark.py pdf path/to/report.pdf --repeat 3 --pages 1-5
```

Save results for your README, release notes, or launch posts:

```bash
python benchmarks/run_benchmark.py img path/to/scan.png \
  --repeat 5 \
  --markdown-out benchmarks/results/image-benchmark.md \
  --json-out benchmarks/results/image-benchmark.json
```

## Compare against other tools

External commands are shell-executed. Use `{input}` for the source file and `{output}` if the tool needs a destination path.

Example with Tesseract:

```bash
python benchmarks/run_benchmark.py img path/to/scan.png \
  --repeat 5 \
  --compare "tesseract=tesseract {input} stdout"
```

Example with a PDF CLI that writes to a file:

```bash
python benchmarks/run_benchmark.py pdf path/to/report.pdf \
  --repeat 3 \
  --compare "other-tool=other-tool --input {input} --output {output}"
```

## Recommended methodology

- Use the same input files for every tool.
- Run at least one warm-up pass before measuring.
- Keep PDF page ranges fixed when comparing runs.
- Separate text-layer PDFs from scanned PDFs in your results.
- Record hardware, OS, Python version, and Chrome version alongside the numbers.

## Good benchmark assets for launches

- One clean image benchmark
- One scanned PDF benchmark
- One mixed-layout PDF benchmark with table and heading reconstruction
- One side-by-side output snippet that shows Markdown quality, not just speed
