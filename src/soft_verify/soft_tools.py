from __future__ import annotations

import mimetypes
import os
import requests
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from pypdf import PdfReader
import base64




TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_workspace",
        "description": "List top-level entries in a workspace directory (non-recursive).",
        "input_schema": {
            "type": "object",
            "properties": {"workspace_path": {"type": "string"}},
            "required": ["workspace_path"],
        },
    },
    {
        "name": "glob_files",
        "description": "Find matching paths by glob.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string"},
                "patterns": {"type": "array", "items": {"type": "string"}},
                "max_results_per_pattern": {"type": "integer"},
                "files_only": {"type": "boolean"},
            },
            "required": ["workspace_path", "patterns"],
        },
    },
    {
        "name": "file_stat",
        "description": "Return basic file metadata.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "markdown_convert",
        "description": "Convert a local file to compact Markdown via markitdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_pdf_preview",
        "description": "Extract a short text preview from the first few pages of a PDF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_pages": {"type": "integer"},
                "max_chars_per_page": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "PaddleOCR",
        "description": "Extract text from an image or PDF using layout parsing OCR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "fileType": {
                    "type": "integer",
                    "description": "For PDF documents, set to 0; for images, set to 1"
                },
            },
            "required": ["path", "fileType"],
        },
    },
]



def list_workspace(workspace_path: str) -> dict[str, Any]:
    root = Path(workspace_path)
    if not root.exists() or not root.is_dir():
        return {
            "workspace_path": str(root),
            "exists": False,
            "entries": [],
            "entry_count": 0,
        }

    entries: list[str] = []
    for path in root.iterdir():
        name = path.name + ("/" if path.is_dir() else "")
        entries.append(name)
    entries.sort()
    return {
        "workspace_path": str(root),
        "exists": True,
        "entries": entries,
        "entry_count": len(entries),
    }


def glob_files(
    workspace_path: str,
    patterns: list[str],
    *,
    max_results_per_pattern: int = 200,
    files_only: bool = True,
) -> dict[str, Any]:
    root = Path(workspace_path)
    limit = max(1, int(max_results_per_pattern))
    matches: dict[str, list[str]] = {}
    for pattern in patterns:
        raw_paths = root.glob(pattern)
        collected: list[str] = []
        total = 0
        for path in raw_paths:
            if files_only and not path.is_file():
                continue
            total += 1
            if len(collected) < limit:
                collected.append(str(path.relative_to(root)))
        _ = total
        matches[str(pattern)] = sorted(collected)
    return {"matches": matches}


def file_stat(path: str) -> dict[str, Any]:
    target = Path(path)
    exists = target.exists()
    return {
        "path": str(target),
        "exists": exists,
        "is_file": target.is_file() if exists else False,
        "size_bytes": int(target.stat().st_size) if exists and target.is_file() else 0,
        "suffix": target.suffix.lower(),
        "mime_type": mimetypes.guess_type(str(target))[0] or "application/octet-stream",
    }


def markdown_convert(path: str, *, max_chars: int = 8000) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"file not found: {target}")
    markitdown_executable = shutil.which("markitdown")
    command = (
        [markitdown_executable, str(target)]
        if markitdown_executable
        else [sys.executable, "-m", "markitdown", str(target)]
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        # Fallback for plain-text-like files when markitdown does not support
        # a specific extension (e.g. .js in some versions).
        text_like_suffixes = {
            ".txt",
            ".md",
            ".markdown",
            ".log",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".csv",
            ".html",
            ".htm",
            ".ini",
            ".cfg",
            ".toml",
            ".sql",
            ".sh",
            ".bat",
        }
        if target.suffix.lower() in text_like_suffixes:
            text = target.read_text(encoding="utf-8", errors="ignore")
            return {
                "path": str(target),
                "chars": len(text),
                "truncated": len(text) > int(max_chars),
                "markdown_preview": text[: int(max_chars)],
            }
        detail = stderr or stdout or f"markitdown exited with code {completed.returncode}"
        raise RuntimeError(detail)
    markdown = completed.stdout or ""
    return {
        "path": str(target),
        "chars": len(markdown),
        "truncated": len(markdown) > int(max_chars),
        "markdown_preview": markdown[: int(max_chars)],
    }


def read_pdf_preview(path: str, *, max_pages: int = 3, max_chars_per_page: int = 2000) -> dict[str, Any]:
    target = Path(path)
    reader = PdfReader(str(target))
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages[:max_pages], start=1):
        text = page.extract_text() or ""
        pages.append(
            {
                "page": index,
                "chars": len(text),
                "preview": text[:max_chars_per_page],
            }
        )
    return {
        "path": str(target),
        "page_count": len(reader.pages),
        "pages": pages,
    }


def PaddleOCR(path: str, fileType: int) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"file not found: {target}")
    
    with open(target, "rb") as file:
        file_bytes = file.read()
        file_data = base64.b64encode(file_bytes).decode("ascii")

    API_URL = "https://g0c6g940h9h346nb.aistudio-app.com/layout-parsing"
    TOKEN = os.environ.get("PADDLEOCR_AISTUDIO_ACCESS_TOKEN")
    if not TOKEN:
        raise ValueError("PADDLEOCR_AISTUDIO_ACCESS_TOKEN environment variable is not set")

    headers = {
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json"
    }

    required_payload = {
        "file": file_data,
        "fileType": fileType,
    }

    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    payload = {**required_payload, **optional_payload}

    response = requests.post(API_URL, json=payload, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"OCR failed with status code {response.status_code}")
        
    result = response.json().get("result", {})
    
    ocr_texts = []
    for res in result.get("layoutParsingResults", []):
        if "markdown" in res and "text" in res["markdown"]:
            ocr_texts.append(res["markdown"]["text"])
            
    return {
        "path": str(target),
        "text": "\\n\\n".join(ocr_texts)
    }


def run_soft_tool_call(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    tool_runners = {
        "list_workspace": list_workspace,
        "glob_files": glob_files,
        "file_stat": file_stat,
        "markdown_convert": markdown_convert,
        "read_pdf_preview": read_pdf_preview,
        "PaddleOCR": PaddleOCR,
    }
    tool_name = str(name or "").strip()
    if tool_name not in tool_runners:
        return {
            "tool_name": tool_name,
            "ok": False,
            "error": f"unknown tool: {tool_name}",
            "result": None,
        }
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return {
            "tool_name": tool_name,
            "ok": False,
            "error": "tool arguments must be an object",
            "result": None,
        }
    try:
        result = tool_runners[tool_name](**arguments)
        return {
            "tool_name": tool_name,
            "ok": True,
            "error": "",
            "result": result,
        }
    except Exception as exc:
        return {
            "tool_name": tool_name,
            "ok": False,
            "error": str(exc),
            "result": None,
        }


def get_soft_tool_definitions() -> list[dict[str, Any]]:
    return [dict(item) for item in TOOL_DEFINITIONS]
