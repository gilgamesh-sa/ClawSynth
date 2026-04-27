#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TS_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")


def extract_text(content):
    """Extract text content from a string or an OpenAI message content list."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    texts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(item.get("text", ""))
    return "\n".join(texts).strip()


def normalize_query(text):
    text = extract_text(text).strip()
    text = TS_PREFIX_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_workspace_path(workspace_dir, workspace_hub_dir, workspace_base):
    try:
        workspace_relative = workspace_dir.relative_to(workspace_hub_dir)
    except ValueError:
        workspace_relative = Path(workspace_dir.name)

    return str(workspace_base / f"{workspace_relative}_workspace")


def load_query_workspace_map(workspace_hub_dir, workspace_base):
    query_to_workspace = {}

    if not workspace_hub_dir.exists():
        print(f"workspace_hub_dir not found: {workspace_hub_dir}")
        return query_to_workspace

    print("Loading Query -> Workspace mapping...")
    workspace_count = 0
    duplicate_count = 0

    for workspace_dir in sorted(workspace_hub_dir.iterdir()):
        if not workspace_dir.is_dir():
            continue

        queries_file = workspace_dir / "queries_persona.jsonl"
        if not queries_file.exists():
            queries_file = workspace_dir / "queries.jsonl"
        if not queries_file.exists():
            continue

        workspace_count += 1
        workspace_label = build_workspace_path(workspace_dir, workspace_hub_dir, workspace_base)

        with open(queries_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                query_text = data.get("result") or data.get("query")
                normalized_query = normalize_query(query_text)
                if not normalized_query:
                    continue

                if normalized_query in query_to_workspace and query_to_workspace[normalized_query] != workspace_label:
                    duplicate_count += 1
                    continue

                query_to_workspace[normalized_query] = workspace_label

    print(f"Loaded {workspace_count} workspaces successfully and built {len(query_to_workspace)} query mappings.")
    if duplicate_count:
        print(f"Detected {duplicate_count} duplicate queries across workspaces; kept the first mapping encountered.")

    return query_to_workspace


def process_trajectory(line_str, query_to_workspace):
    try:
        data = json.loads(line_str)
    except json.JSONDecodeError:
        return None

    messages = data.get("messages", [])
    if not messages:
        return None

    query = ""
    last_content = ""

    for msg in messages:
        if msg.get("role") == "user":
            query = normalize_query(msg.get("content", ""))
            break

    if not query or query not in query_to_workspace:
        return None

    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            text = extract_text(msg.get("content", ""))
            if text:
                last_content = text
                break

    return {
        "intent": query,
        "workspace": query_to_workspace[query],
        "agent_final_output": last_content,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract intent/workspace/agent_final_output for checking")
    parser.add_argument("--input_file", required=True, help="Path to the input jsonl file containing trajectory data processed by process_conversations")
    parser.add_argument("--workspace_hub_dir", required=True, help="Root directory of the workspace hub")
    parser.add_argument("--workspace_base", required=True, help="Root directory of the real workspaces")
    parser.add_argument("--output_file", required=True, help="Path to the output jsonl file")
    args = parser.parse_args()

    input_file = Path(args.input_file)
    workspace_hub_dir = Path(args.workspace_hub_dir)
    workspace_base = Path(args.workspace_base)
    output_file = Path(args.output_file)

    if not input_file.exists():
        print(f"Input file not found: {input_file}")
        sys.exit(1)

    query_to_workspace = load_query_workspace_map(workspace_hub_dir, workspace_base)

    print(f"Starting to parse trajectory file: {input_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    processed = 0
    with open(input_file, "r", encoding="utf-8") as f, open(output_file, "w", encoding="utf-8") as out_f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            result = process_trajectory(line, query_to_workspace)
            if result:
                out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                processed += 1

    print(f"Parsing complete. Successfully matched and processed {processed} records.")
    print(f"Extraction results have been saved to: {output_file}")


if __name__ == "__main__":
    main()
