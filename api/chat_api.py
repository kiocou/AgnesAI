from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from api.client import AgnesAPIError, AgnesClient


@dataclass
class ChatResult:
    content: str
    raw: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""
    delta: str = ""
    role: str = ""
    finish_reason: str = ""
    tool_calls_delta: list[dict[str, Any]] = field(default_factory=list)


class ChatGenerator:
    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str = "agnes-2.0-flash",
        temperature: float = 0.7,
        top_p: float | None = None,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        data = self.client.request("POST", "/chat/completions", json_payload=payload, timeout=180)
        return self._parse_response(data)

    def stream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str = "agnes-2.0-flash",
        temperature: float = 0.7,
        top_p: float | None = None,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Generator[StreamChunk, None, None]:
        """Send a streaming chat completion request, yielding StreamChunk objects."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        for data_str in self.client.stream_request("POST", "/chat/completions", json_payload=payload, timeout=300):
            try:
                chunk_data = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                continue

            choices = chunk_data.get("choices")
            if not isinstance(choices, list) or not choices:
                continue

            delta = choices[0].get("delta", {})
            yield StreamChunk(
                delta=delta.get("content", "") or "",
                role=delta.get("role", "") or "",
                finish_reason=choices[0].get("finish_reason", "") or "",
                tool_calls_delta=delta.get("tool_calls", []) or [],
            )

    @staticmethod
    def _parse_response(data: Any) -> ChatResult:
        if not isinstance(data, dict):
            raise AgnesAPIError("对话接口返回格式异常。", raw=data)

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = (message.get("content") or "").strip()
                    tool_calls = message.get("tool_calls") or []
                    if content or tool_calls:
                        return ChatResult(content=content, raw=data, tool_calls=tool_calls)
                if first.get("text"):
                    return ChatResult(content=str(first["text"]).strip(), raw=data)

        for key in ("content", "text", "output_text", "answer"):
            if data.get(key):
                return ChatResult(content=str(data[key]).strip(), raw=data)

        raise AgnesAPIError("对话完成但响应中没有文本内容。", raw=data)
