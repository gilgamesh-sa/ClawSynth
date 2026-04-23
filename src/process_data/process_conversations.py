#!/usr/bin/env python3
"""
将网关抓取数据处理成通用格式，方便阅读。
处理 success_events_all.jsonl 文件:
1. 按 user query 分组，保留每组中 messages 最长的记录
2. 只保留 messages 和 tools 字段
3. 将 response_obj 中的模型回复解析后拼到 messages 最后
4. 统一 messages 格式为 [{"role": "system", "content": xxx}, {"role": "user", "content": xxx}, ...]
5. 合并连续的 tool role 消息
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
                # [{"type": "text", "text": "..."}] 格式
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
    """从 response_obj 解析出最终的 assistant 回复消息"""
    choices = response_obj.get("choices", [])
    if not choices:
        return None

    msg = choices[0].get("message", {})
    result = {"role": "assistant"}

    # 处理 content
    content = normalize_content(msg.get("content"))
    if content:
        result["content"] = content

    # 保留思考过程
    reasoning = msg.get("reasoning_content")
    if reasoning:
        result["reasoning_content"] = reasoning

    # 处理 tool_calls
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

    # 保留 assistant 的 tool_calls 和思考过程
    if role == "assistant":
        if msg.get("tool_calls"):
            result["tool_calls"] = msg["tool_calls"]
        reasoning = msg.get("reasoning_content")
        if reasoning:
            result["reasoning_content"] = reasoning

    # 保留 tool 的 tool_call_id 和 name
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
            # 收集所有连续的 tool 消息
            tool_group = [msg]
            j = i + 1
            while j < len(messages) and messages[j]["role"] == "tool":
                tool_group.append(messages[j])
                j += 1

            if len(tool_group) == 1:
                # 单条 tool 消息，直接保留
                merged.append(msg)
            else:
                # 多条连续 tool 消息，合并为列表格式
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

    # 1. 标准化每条 message
    normalized = [normalize_message(m) for m in messages]

    # 2. 解析 response_obj 拼到最后
    resp_msg = parse_response_message(response_obj)
    if resp_msg:
        normalized.append(resp_msg)

    # 3. 合并连续的 tool 消息
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

    print(f"读取文件: {input_file}")

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
                print(f"  跳过第 {line_num + 1} 行 (JSON 解析错误): {e}")
                continue

            query = extract_user_query(record.get("messages", []))
            msg_count = len(record.get("messages", []))
            query_groups[query].append((msg_count, line_num, record))
            line_count += 1

            if line_count % 500 == 0:
                print(f"  已读取 {line_count} 条记录...")

    print(f"总共读取 {line_count} 条记录, {len(query_groups)} 个不同的 query")

    output_count = 0
    with open(output_file, "w", encoding="utf-8") as f:
        for query, group in query_groups.items():
            # 按 messages 数量降序排列，取最长的
            group.sort(key=lambda x: x[0], reverse=True)
            best_msg_count, best_line, best_record = group[0]

            # 处理这条记录
            processed = process_record(best_record)
            f.write(json.dumps(processed, ensure_ascii=False) + "\n")
            output_count += 1

    print(f"处理完成! 输出 {output_count} 条记录到: {output_file}")
    print(f"去重比例: {line_count} -> {output_count} ({output_count/line_count*100:.1f}%)")


if __name__ == "__main__":
    main()
