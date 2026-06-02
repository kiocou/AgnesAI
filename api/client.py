from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import requests

from utils.logging_utils import LOGGER


class AgnesAPIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        raw: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.raw = raw


@dataclass
class AgnesClient:
    api_key: str
    base_url: str = "https://apihub.agnes-ai.com/v1"
    timeout: int = 180

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise AgnesAPIError("请先填写并保存 API Key。", status_code=None)
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _reset_session(self) -> None:
        """Close and recreate the HTTP session (fixes stale/corrupted connection pools)."""
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        LOGGER.info("HTTP session reset (connection pool cleared)")

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        # Build a safe log payload that truncates large base64 fields
        log_payload: dict[str, Any] = {}
        for _k, _v in (json_payload or {}).items():
            if isinstance(_v, str) and len(_v) > 500 and (_v.startswith("data:") or "base64" in _k):
                log_payload[_k] = f"{_v[:80]}...[{len(_v)} chars]"
            else:
                log_payload[_k] = _v
        LOGGER.info("API request %s %s payload=%s", method.upper(), url, json.dumps(log_payload, ensure_ascii=False))

        for attempt in range(2):
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=self._headers(),
                    json=json_payload,
                    timeout=timeout or self.timeout,
                )
                break
            except requests.Timeout as exc:
                LOGGER.error("API timeout %s %s", method.upper(), url)
                raise AgnesAPIError("网络超时，请稍后重试。") from exc
            except requests.ConnectionError as exc:
                if attempt == 0:
                    LOGGER.warning("API connection error (attempt 1/2), resetting session and retrying...")
                    self._reset_session()
                    continue
                LOGGER.error("API connection error %s %s (after retry)", method.upper(), url)
                raise AgnesAPIError("网络连接失败，请检查网络或 Base URL。") from exc
            except requests.RequestException as exc:
                LOGGER.exception("API request failed")
                raise AgnesAPIError(f"请求失败：{exc}") from exc

        text_preview = response.text[:2000]
        LOGGER.info(
            "API response %s %s status=%s body=%s",
            method.upper(),
            url,
            response.status_code,
            text_preview,
        )

        if response.status_code >= 400:
            raise self._error_from_response(response)

        if not response.text.strip():
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise AgnesAPIError("服务端返回了非 JSON 数据。", response.status_code) from exc

    def stream_request(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Generator[str, None, None]:
        """Send a streaming request and yield SSE data chunks as they arrive."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        safe_payload = json.dumps(json_payload or {}, ensure_ascii=False)
        LOGGER.info("Stream request %s %s payload=%s", method.upper(), url, safe_payload)

        headers = self._headers()
        headers["Accept"] = "text/event-stream"

        for attempt in range(2):
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=json_payload,
                    timeout=timeout or self.timeout,
                    stream=True,
                )
                break
            except requests.Timeout as exc:
                raise AgnesAPIError("网络超时，请稍后重试。") from exc
            except requests.ConnectionError as exc:
                if attempt == 0:
                    LOGGER.warning("Stream connection error (attempt 1/2), resetting session and retrying...")
                    self._reset_session()
                    continue
                raise AgnesAPIError("网络连接失败，请检查网络或 Base URL。") from exc
            except requests.RequestException as exc:
                raise AgnesAPIError(f"请求失败：{exc}") from exc

        if response.status_code >= 400:
            # Consume the body so error parsing can access response.text
            _ = response.content
            raise self._error_from_response(response)

        # ── Low-latency SSE parser ──
        # iter_lines() uses a 512-byte internal buffer which introduces
        # artificial delay for small SSE events (typical of LLM token
        # streaming).  We read in small chunks and yield each complete line
        # the instant its trailing newline arrives on the wire.
        buf = bytearray()
        try:
            for raw_bytes in response.iter_content(chunk_size=1024):
                if not raw_bytes:
                    continue
                buf.extend(raw_bytes)
                # Process all complete lines in the buffer
                while True:
                    nl = -1
                    for i, b in enumerate(buf):
                        if b == 0x0A or b == 0x0D:  # \n or \r
                            nl = i
                            break
                    if nl < 0:
                        break
                    try:
                        line = buf[:nl].decode("utf-8").strip()
                    except UnicodeDecodeError:
                        line = buf[:nl].decode("utf-8", errors="replace").strip()
                    # Skip past the newline (and \r\n pair)
                    skip = nl + 1
                    if skip < len(buf) and buf[nl] == 0x0D and buf[skip] == 0x0A:
                        skip += 1
                    buf = buf[skip:]
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            return
                        yield data_str
        except requests.exceptions.ChunkedEncodingError:
            # Connection closed mid-stream — yield any remaining buffered line
            if buf:
                try:
                    line = buf.decode("utf-8", errors="replace").strip()
                except Exception:
                    line = ""
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() != "[DONE]":
                        yield data_str

    def _error_from_response(self, response: requests.Response) -> AgnesAPIError:
        status = response.status_code
        message = response.text.strip() or f"HTTP {status}"
        raw: Any = response.text

        try:
            raw = response.json()
            if isinstance(raw, dict):
                # Try multiple extraction strategies
                extracted = (
                    # 1. Top-level "message" field
                    raw.get("message")
                    # 2. Nested error.message
                    or (raw.get("error", {}).get("message") if isinstance(raw.get("error"), dict) else None)
                    # 3. error as string
                    or (raw.get("error") if isinstance(raw.get("error"), str) else None)
                    # 4. Top-level "detail"
                    or raw.get("detail")
                    # 5. Top-level "code" + "message" combo
                    or (f"[{raw['code']}] {raw.get('message', '')}" if "code" in raw else None)
                    # 6. Fallback
                    or message
                )
                if isinstance(extracted, str) and extracted.strip():
                    message = extracted.strip()
            elif isinstance(raw, str):
                message = raw
        except (ValueError, AttributeError):
            pass

        lower = str(message).lower()
        if status == 401:
            message = f"401 鉴权失败：{message}"
        elif status == 403:
            message = "403 无权限：账号或模型权限不足。"
        elif status == 429:
            message = "429 请求过多：触发限流，请稍后重试。"
        elif status in (500, 503):
            message = f"{status} 服务异常：Agnes 服务暂时不可用。"
        elif any(word in lower for word in ("balance", "credit", "quota", "余额")):
            message = "API 余额不足或额度已用尽。"

        return AgnesAPIError(message, status_code=status, raw=raw)
