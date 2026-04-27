from __future__ import annotations

import mimetypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from soft_verify.soft_tools import (
    TOOL_DEFINITIONS,
    get_soft_tool_definitions,
    run_soft_tool_call,
)

FILES_DIR = Path(__file__).resolve().parent / "files"


def _file(name: str) -> str:
    return str(FILES_DIR / name)


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_entries"),
    [
        (
            "list_workspace",
            {"workspace_path": str(FILES_DIR)},
            {"exists": True, "entry_count_min": 1},
        ),
        (
            "file_stat",
            {"path": _file("sample.txt")},
            {"exists": True, "is_file": True, "suffix": ".txt"},
        ),
    ],
)
def test_tools_return_expected_basic_shapes(
    tool_name: str,
    args: dict[str, object],
    expected_entries: dict[str, object],
) -> None:
    result = run_soft_tool_call(tool_name, args)

    assert result["ok"] is True
    assert result["error"] == ""
    assert isinstance(result["result"], dict)

    payload = result["result"]
    for key, value in expected_entries.items():
        if key == "entry_count_min":
            assert payload["entry_count"] >= value
        else:
            assert payload[key] == value


def test_get_soft_tool_definitions_matches_registered_tools() -> None:
    definitions = get_soft_tool_definitions()

    assert definitions == TOOL_DEFINITIONS
    assert {item["name"] for item in definitions} == {
        "list_workspace",
        "glob_files",
        "file_stat",
        "markdown_convert",
        "read_pdf_preview",
        "PaddleOCR",
    }


def test_list_workspace_for_missing_directory() -> None:
    missing_dir = FILES_DIR / "does_not_exist"

    result = run_soft_tool_call("list_workspace", {"workspace_path": str(missing_dir)})

    assert result["ok"] is True
    assert result["result"] == {
        "workspace_path": str(missing_dir),
        "exists": False,
        "entries": [],
        "entry_count": 0,
    }


def test_glob_files_returns_relative_matches() -> None:
    result = run_soft_tool_call(
        "glob_files",
        {
            "workspace_path": str(FILES_DIR),
            "patterns": ["*.txt", "*.md"],
        },
    )

    assert result["ok"] is True
    assert result["result"] == {
        "matches": {
            "*.txt": ["sample.txt"],
            "*.md": ["sample.md"],
        }
    }


def test_file_stat_for_missing_file() -> None:
    missing_file = FILES_DIR / "missing.xyz"

    result = run_soft_tool_call("file_stat", {"path": str(missing_file)})

    assert result["ok"] is True
    assert result["result"]["path"] == str(missing_file)
    assert result["result"]["exists"] is False
    assert result["result"]["is_file"] is False
    assert result["result"]["size_bytes"] == 0
    assert result["result"]["suffix"] == ".xyz"
    assert result["result"]["mime_type"] == (
        mimetypes.guess_type(str(missing_file))[0] or "application/octet-stream"
    )


def test_markdown_convert_uses_markitdown_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_which(name: str) -> str:
        assert name == "markitdown"
        return "/usr/bin/markitdown"

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="# Converted\n\nhello", stderr="")

    monkeypatch.setattr("soft_verify.soft_tools.shutil.which", fake_which)
    monkeypatch.setattr("soft_verify.soft_tools.subprocess.run", fake_run)

    result = run_soft_tool_call("markdown_convert", {"path": _file("sample.md")})

    assert result["ok"] is True
    assert result["result"]["markdown_preview"] == "# Converted\n\nhello"
    assert captured["command"] == ["/usr/bin/markitdown", _file("sample.md")]


def test_markdown_convert_falls_back_to_plain_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text_file = tmp_path / "note.txt"
    text_file.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    monkeypatch.setattr("soft_verify.soft_tools.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "soft_verify.soft_tools.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="markitdown failed",
        ),
    )

    result = run_soft_tool_call(
        "markdown_convert",
        {"path": str(text_file), "max_chars": 5},
    )

    assert result["ok"] is True
    assert result["result"] == {
        "path": str(text_file),
        "chars": len("alpha\nbeta\ngamma\n"),
        "truncated": True,
        "markdown_preview": "alpha",
    }


def test_markdown_convert_reports_error_for_missing_file() -> None:
    result = run_soft_tool_call("markdown_convert", {"path": _file("missing.md")})

    assert result["ok"] is False
    assert "file not found" in result["error"]
    assert result["result"] is None


def test_read_pdf_preview_extracts_expected_text() -> None:
    result = run_soft_tool_call("read_pdf_preview", {"path": _file("sample.pdf")})

    assert result["ok"] is True
    assert result["result"]["path"] == _file("sample.pdf")
    assert result["result"]["page_count"] == 1
    assert result["result"]["pages"][0]["page"] == 1
    assert "hello" in result["result"]["pages"][0]["preview"].lower()


def test_run_soft_tool_call_rejects_unknown_tool() -> None:
    result = run_soft_tool_call("unknown_tool_xyz", {})

    assert result == {
        "tool_name": "unknown_tool_xyz",
        "ok": False,
        "error": "unknown tool: unknown_tool_xyz",
        "result": None,
    }


def test_run_soft_tool_call_rejects_non_object_arguments() -> None:
    result = run_soft_tool_call("file_stat", "not-a-dict")

    assert result == {
        "tool_name": "file_stat",
        "ok": False,
        "error": "tool arguments must be an object",
        "result": None,
    }


def test_paddleocr_requires_file_type_argument() -> None:
    result = run_soft_tool_call("PaddleOCR", {"path": _file("sample.png")})

    assert result["ok"] is False
    assert "fileType" in result["error"]


def test_paddleocr_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PADDLEOCR_AISTUDIO_ACCESS_TOKEN", raising=False)

    result = run_soft_tool_call(
        "PaddleOCR",
        {"path": _file("sample.png"), "fileType": 1},
    )

    assert result["ok"] is False
    assert "PADDLEOCR_AISTUDIO_ACCESS_TOKEN" in result["error"]


def test_paddleocr_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "line one"}},
                        {"markdown": {"text": "line two"}},
                    ]
                }
            }

    def fake_post(url: str, json: dict[str, object], headers: dict[str, str]) -> FakeResponse:
        assert url.endswith("/layout-parsing")
        assert json["fileType"] == 1
        assert headers["Authorization"] == "token fake-token"
        return FakeResponse()

    monkeypatch.setenv("PADDLEOCR_AISTUDIO_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr("soft_verify.soft_tools.requests.post", fake_post)

    result = run_soft_tool_call(
        "PaddleOCR",
        {"path": _file("sample.png"), "fileType": 1},
    )

    assert result["ok"] is True
    assert result["result"] == {
        "path": _file("sample.png"),
        "text": "line one\\n\\nline two",
    }
