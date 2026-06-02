from __future__ import annotations

import base64
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from urllib.parse import quote as _url_quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from api.client import AgnesAPIError, AgnesClient
from utils.logging_utils import LOGGER

# Public proxy for Google Cloud Storage (blocked in some regions)
_GCS_PROXY = "https://api.codetabs.com/v1/proxy?quest="


@dataclass
class ImageResult:
    url: str | None = None
    b64_json: str | None = None
    revised_prompt: str | None = None
    raw: dict[str, Any] | None = None


def _create_retry_session(max_retries: int = 3) -> requests.Session:
    """Create a requests session with automatic retry on connection failures."""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=1,  # 1s, 2s, 4s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=4,
        pool_maxsize=4,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class ImageGenerator:
    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        model: str = "agnes-image-2.1-flash",
        size: str = "1024x1024",
        count: int = 1,
        seed: int | None = None,
    ) -> list[ImageResult]:
        request_count = max(1, min(int(count), 4))
        results: list[ImageResult] = []
        for _ in range(request_count):
            payload: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "size": size,
            }
            if negative_prompt.strip():
                payload["negative_prompt"] = negative_prompt.strip()
            if seed is not None:
                payload["seed"] = seed

            data = self.client.request("POST", "/images/generations", json_payload=payload)
            results.extend(self._parse_results(data))
        return results

    def save_image(self, source_path: str | Path, target_path: str | Path) -> Path:
        source = Path(source_path)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        LOGGER.info("Saved image %s -> %s", source, target)
        return target

    def download_image(
        self,
        result: ImageResult | str,
        target_path: str | Path,
        *,
        timeout: int = 180,
        max_retries: int = 3,
    ) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(result, ImageResult):
            url = result.url
            b64_json = result.b64_json
        else:
            url = result
            b64_json = None

        if b64_json:
            target.write_bytes(base64.b64decode(b64_json))
            LOGGER.info("Downloaded base64 image to %s", target)
            return target

        if not url:
            raise AgnesAPIError("图片结果中没有可下载的 URL 或 base64 数据。")

        if url.startswith("data:image"):
            _, encoded = url.split(",", 1)
            target.write_bytes(base64.b64decode(encoded))
            LOGGER.info("Downloaded data URI image to %s", target)
            return target

        # Retry logic for connection stability
        last_error: Exception | None = None
        session = _create_retry_session(max_retries=max_retries)

        # Build URL list: direct URL first, then GCS proxy fallback if applicable
        urls_to_try = [url]
        if "storage.googleapis.com" in url:
            proxy_url = f"{_GCS_PROXY}{_url_quote(url, safe='')}"
            urls_to_try.append(proxy_url)

        for try_url in urls_to_try:
            for attempt in range(max_retries):
                try:
                    with session.get(try_url, stream=True, timeout=timeout) as response:
                        response.raise_for_status()
                        with target.open("wb") as fh:
                            for chunk in response.iter_content(chunk_size=1024 * 128):
                                if chunk:
                                    fh.write(chunk)
                    LOGGER.info("Downloaded image %s -> %s", try_url[:80], target)
                    return target
                except (requests.ConnectionError, requests.Timeout, ConnectionError, OSError) as exc:
                    last_error = exc
                    LOGGER.warning(
                        "Image download attempt %d/%d failed for %s: %s",
                        attempt + 1, max_retries, try_url[:60], exc,
                    )
                    # Clean up partial file
                    if target.exists():
                        target.unlink()
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt  # 1s, 2s, 4s
                        LOGGER.info("Retrying in %ds...", wait)
                        time.sleep(wait)
                except requests.RequestException as exc:
                    LOGGER.exception("Image download failed (non-retryable)")
                    raise AgnesAPIError(f"图片下载失败：{exc}") from exc

            # If direct URL exhausted all retries and we have a proxy URL, try it
            if try_url == url and len(urls_to_try) > 1:
                LOGGER.warning("Direct GCS download failed, trying proxy fallback...")

        # All retries exhausted
        LOGGER.error("Image download failed after all retries")
        raise AgnesAPIError(f"图片下载失败（已重试 {max_retries} 次）：{last_error}")

    def _parse_results(self, data: Any) -> list[ImageResult]:
        if isinstance(data, dict):
            items = data.get("data") or data.get("images") or data.get("output")
            if isinstance(items, list):
                results = [self._item_to_result(item) for item in items]
                return [item for item in results if item.url or item.b64_json]

            single = self._item_to_result(data)
            if single.url or single.b64_json:
                return [single]

        raise AgnesAPIError("图片生成成功但响应中没有找到图片结果。", raw=data)

    @staticmethod
    def _item_to_result(item: Any) -> ImageResult:
        if isinstance(item, str):
            return ImageResult(url=item)
        if not isinstance(item, dict):
            return ImageResult()

        url = (
            item.get("url")
            or item.get("image_url")
            or item.get("result_url")
            or item.get("download_url")
        )
        return ImageResult(
            url=url,
            b64_json=item.get("b64_json") or item.get("base64"),
            revised_prompt=item.get("revised_prompt"),
            raw=item,
        )
