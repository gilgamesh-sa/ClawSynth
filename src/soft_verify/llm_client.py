from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import llm_config
from .prompts import (
    DIRECT_RULE_PLAN_SYSTEM_PROMPT,
    SOFT_CHECK_AGENT_SYSTEM_PROMPT,
)


class LLMClientError(RuntimeError):
    pass


def _request_completion(
    *,
    system_prompt: str,
    config: dict[str, str | int],
    json_mode: bool,
    user_prompt: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    api_key = str(config["api_key"])

    url = f"{config['base_url']}/chat/completions"
    if messages is None:
        if user_prompt is None:
            raise LLMClientError("user_prompt is required when messages is not provided")
        final_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        final_messages = [{"role": "system", "content": system_prompt}] + [
            dict(item) for item in messages if isinstance(item, dict)
        ]
    # Do not force temperature; let the model/provider use its default.
    body = {"model": config["model_name"], "messages": final_messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(config["timeout_seconds"])) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise LLMClientError(f"LLM HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMClientError(f"LLM request failed: {exc}") from exc

    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError(f"LLM response format invalid: {payload}") from exc
    if not isinstance(message, dict):
        raise LLMClientError(f"LLM response message invalid: {message}")
    message["_request_messages"] = final_messages
    return message


def _extract_last_json_object(content: str) -> dict:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced_markers = ["```json", "```JSON", "```"]
    for marker in fenced_markers:
        marker_index = content.rfind(marker)
        if marker_index < 0:
            continue
        after_marker = content[marker_index + len(marker):]
        end_index = after_marker.find("```")
        if end_index < 0:
            continue
        candidate = after_marker[:end_index].strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    decoder = json.JSONDecoder()
    for index in range(len(content) - 1, -1, -1):
        if content[index] != "{":
            continue
        candidate = content[index:].strip()
        try:
            parsed, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if candidate[end:].strip():
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMClientError(f"LLM did not return valid JSON: {content}")


def _complete_json(*, system_prompt: str, user_prompt: str, config: dict[str, str | int]) -> dict:
    message = _request_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        config=config,
        json_mode=True,
    )
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMClientError(f"LLM response content invalid: {content}")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        try:
            return _extract_last_json_object(content)
        except LLMClientError:
            raise LLMClientError(f"LLM did not return valid JSON: {content}") from exc


def generate_direct_rule_plan(user_prompt: str) -> dict:
    return _complete_json(system_prompt=DIRECT_RULE_PLAN_SYSTEM_PROMPT, user_prompt=user_prompt, config=llm_config())


def _tool_schema_for_api(available_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for item in available_tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or ""),
                    "parameters": item.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return schemas


def _parse_native_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = message.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        return []
    parsed_calls: list[dict[str, Any]] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        function_data = item.get("function", {})
        if not isinstance(function_data, dict):
            continue
        name = str(function_data.get("name") or "").strip()
        if not name:
            continue
        arguments = function_data.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        parsed_calls.append(
            {
                "id": str(item.get("id") or "").strip(),
                "name": name,
                "arguments": arguments,
            }
        )
    return parsed_calls


def _parse_results_from_message_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return []
    try:
        parsed = _extract_last_json_object(content)
    except LLMClientError:
        return []
    raw_results = parsed.get("results", [])
    if not isinstance(raw_results, list):
        return []
    return [item for item in raw_results if isinstance(item, dict)]


def judge_soft_checks_with_agent(
    user_prompt: str | None = None,
    *,
    conversation_messages: list[dict[str, Any]] | None = None,
    available_tools: list[dict[str, Any]] | None = None,
) -> dict:
    message = _request_completion(
        system_prompt=SOFT_CHECK_AGENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        messages=conversation_messages,
        config=llm_config(),
        json_mode=False,
        tools=_tool_schema_for_api(available_tools or []),
    )
    tool_calls = _parse_native_tool_calls(message)
    parsed_results = _parse_results_from_message_content(message)
    if tool_calls:
        return {"tool_calls": tool_calls, "results": parsed_results, "_assistant_message": message}
    content = message.get("content", "")
    if not isinstance(content, str):
        raise LLMClientError(f"LLM response content invalid: {content}")
    parsed = _extract_last_json_object(content)
    if "results" not in parsed:
        parsed["results"] = []
    if "tool_calls" not in parsed:
        parsed["tool_calls"] = []
    parsed["_assistant_message"] = message
    return parsed
