from __future__ import annotations

import argparse

import pytest

from chrome_ocr import __version__
from chrome_ocr import cli


class TestParsePagesSpec:
    def test_single_pages_and_ranges(self):
        assert cli.parse_pages_spec("1,3,5-7") == [1, 3, 5, 6, 7]

    def test_deduplicates_while_preserving_order(self):
        assert cli.parse_pages_spec("3,1,3,2-4") == [3, 1, 2, 4]

    @pytest.mark.parametrize("spec", ["", "0", "2-1", "1,,2", "a", "1-b"])
    def test_rejects_invalid_specs(self, spec):
        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_pages_spec(spec)


class TestCliCommands:
    def test_img_command_writes_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "ocr_img", lambda path: f"img:{path}")

        assert cli.main(["img", "scan.png"]) == 0

        assert capsys.readouterr().out == "img:scan.png\n"

    def test_pdf_command_writes_file(self, monkeypatch, tmp_path):
        seen: dict = {}

        def _fake_ocr_pdf(path, *, dpi, pages, page_sep):
            seen["path"] = path
            seen["dpi"] = dpi
            seen["pages"] = pages
            seen["page_sep"] = page_sep
            return "pdf output"

        monkeypatch.setattr(cli, "ocr_pdf", _fake_ocr_pdf)
        output_path = tmp_path / "out.md"

        assert cli.main(
            [
                "pdf",
                "report.pdf",
                "--dpi",
                "300",
                "--pages",
                "1,3-4",
                "--page-sep",
                "\n---\n",
                "-o",
                str(output_path),
            ]
        ) == 0

        assert seen == {
            "path": "report.pdf",
            "dpi": 300,
            "pages": [1, 3, 4],
            "page_sep": "\n---\n",
        }
        assert output_path.read_text(encoding="utf-8") == "pdf output"

    def test_doctor_reports_missing_component(self, monkeypatch, capsys):
        class _MissingEngine:
            @staticmethod
            def _find_dll():
                return None

        monkeypatch.setattr(cli, "ScreenAIEngine", _MissingEngine)

        assert cli.main(["doctor"]) == 1

        out = capsys.readouterr().out
        assert "status: missing" in out
        assert "dll: not found" in out

    def test_doctor_reports_ready_component(self, monkeypatch, capsys):
        class _ReadyEngine:
            max_dimension = 4096
            ok = True

            def __init__(self, dll_path=None):
                self.dll_path = dll_path

            @staticmethod
            def _find_dll():
                return r"C:\Chrome\screen_ai\chrome_screen_ai.dll"

        monkeypatch.setattr(cli, "ScreenAIEngine", _ReadyEngine)

        assert cli.main(["doctor"]) == 0

        out = capsys.readouterr().out
        assert "status: ready" in out
        assert r"dll: C:\Chrome\screen_ai\chrome_screen_ai.dll" in out
        assert "max_image_dimension: 4096" in out

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])

        assert exc.value.code == 0
        assert __version__ in capsys.readouterr().out
