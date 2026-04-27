#!/usr/bin/env python3
"""
Process gateway-captured data into a generic, easier-to-read format.
This script processes `success_events_all.jsonl` by:
1. Grouping records by user query and keeping the record with the longest `messages` in each group.
2. Keeping only the `messages` and `tools` fields.
3. Parsing the model reply from `response_obj` and appending it to the end of `messages`.
4. Normalizing `messages` into the format [{"role": "system", "content": xxx}, {"role": "user", "content": xxx}, ...].
5. Merging consecutive `tool` role messages.
"""

import json
import sys
import argparse
from collections import defaultdict


def extract_user_query(messages):
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # [{"type": "text", "text": "..."}] format
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        return item.get("text", "")
            elif isinstance(content, str):
                return content
    return ""


def normalize_content(content):
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image_url":
                    parts.append(f"[image: {item.get('image_url', {}).get('url', '')}]")
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else ""
    return str(content)


def parse_response_message(response_obj):
    """Parse the final assistant reply message from response_obj."""
    choices = response_obj.get("choices", [])
    if not choices:
        return None

    msg = choices[0].get("message", {})
    result = {"role": "assistant"}

    # Handle content
    content = normalize_content(msg.get("content"))
    if content:
        result["content"] = content

    # Preserve reasoning content
    reasoning = msg.get("reasoning_content")
    if reasoning:
        result["reasoning_content"] = reasoning

    # Handle tool_calls
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        result["tool_calls"] = tool_calls
        if "content" not in result:
            result["content"] = ""

    return result


def normalize_message(msg):
    role = msg.get("role", "")

    # developer -> system
    if role == "developer":
        role = "system"

    result = {"role": role, "content": normalize_content(msg.get("content", ""))}

    # Preserve the assistant's tool_calls and reasoning content
    if role == "assistant":
        if msg.get("tool_calls"):
            result["tool_calls"] = msg["tool_calls"]
        reasoning = msg.get("reasoning_content")
        if reasoning:
            result["reasoning_content"] = reasoning

    # Preserve the tool's tool_call_id and name
    if role == "tool":
        if msg.get("tool_call_id"):
            result["tool_call_id"] = msg["tool_call_id"]
        if msg.get("name"):
            result["name"] = msg["name"]

    return result


def merge_consecutive_tool_messages(messages):
    if not messages:
        return messages

    merged = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "tool":
            # Collect all consecutive tool messages
            tool_group = [msg]
            j = i + 1
            while j < len(messages) and messages[j]["role"] == "tool":
                tool_group.append(messages[j])
                j += 1

            if len(tool_group) == 1:
                # Keep a single tool message as-is
                merged.append(msg)
            else:
                # Merge multiple consecutive tool messages into a list-style payload
                content_list = [
                    {
                        "content": t.get("content", ""),
                        "tool_call_id": t.get("tool_call_id", ""),
                    }
                    for t in tool_group
                ]

                merged_msg = {
                    "role": "tool",
                    "content": content_list,
                }
                merged.append(merged_msg)

            i = j
        else:
            merged.append(msg)
            i += 1

    return merged


def process_record(record):
    messages = record.get("messages", [])
    response_obj = record.get("response_obj", {})
    tools = record.get("tools", [])

    # 1. Normalize each message
    normalized = [normalize_message(m) for m in messages]

    # 2. Parse response_obj and append it to the end
    resp_msg = parse_response_message(response_obj)
    if resp_msg:
        normalized.append(resp_msg)

    # 3. Merge consecutive tool messages
    normalized = merge_consecutive_tool_messages(normalized)

    return {"messages": normalized, "tools": tools}


def main():
    parser = argparse.ArgumentParser(description="Process conversation data.")
    parser.append = parser.add_argument
    parser.append("--input_file", required=True, help="Path to input jsonl file")
    parser.append("--output_file", required=True, help="Path to output jsonl file")
    args = parser.parse_args()

    input_file = args.input_file
    output_file = args.output_file

    print(f"Reading file: {input_file}")

    query_groups = defaultdict(list)
    line_count = 0

    with open(input_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  Skipping line {line_num + 1} (JSON parse error): {e}")
                continue

            query = extract_user_query(record.get("messages", []))
            msg_count = len(record.get("messages", []))
            query_groups[query].append((msg_count, line_num, record))
            line_count += 1

            if line_count % 500 == 0:
                print(f"  Loaded {line_count} records...")

    print(f"Loaded {line_count} records in total, with {len(query_groups)} distinct queries")

    output_count = 0
    with open(output_file, "w", encoding="utf-8") as f:
        for query, group in query_groups.items():
            # Sort by number of messages in descending order and keep the longest one
            group.sort(key=lambda x: x[0], reverse=True)
            best_msg_count, best_line, best_record = group[0]

            # Process this record
            processed = process_record(best_record)
            f.write(json.dumps(processed, ensure_ascii=False) + "\n")
            output_count += 1

    print(f"Processing complete. Wrote {output_count} records to: {output_file}")
    print(f"Deduplication ratio: {line_count} -> {output_count} ({output_count/line_count*100:.1f}%)")


if __name__ == "__main__":
    main()
