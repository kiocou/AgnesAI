from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests
from requests.exceptions import ChunkedEncodingError

from api.client import AgnesAPIError
from utils.logging_utils import LOGGER


ProgressCallback = Callable[[int, int, int], None]


class DownloadManagerBackend:
    """Download backend with resumable retries for flaky media streams."""

    CHUNK_SIZE = 256 * 1024
    MAX_ATTEMPTS = 6
    MAX_BACKOFF_SECONDS = 8
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self) -> None:
        # Reuse a session for connection pooling
        self._session = requests.Session()

    # Public proxy for Google Cloud Storage (blocked in some regions)
    _GCS_PROXY = "https://api.codetabs.com/v1/proxy?quest="

    def download_file(
        self,
        *,
        url: str,
        target_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
        timeout: int = 600,
        max_attempts: int | None = None,
    ) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_path = target.with_suffix(target.suffix + ".part")
        attempts = max(1, int(max_attempts or self.MAX_ATTEMPTS))

        try:
            self._download_with_retries(
                url,
                part_path,
                target,
                attempts,
                progress_callback,
                pause_event,
                cancel_event,
                timeout,
            )
        except requests.RequestException as exc:
            # Retry Google Cloud Storage via proxy if direct download fails
            if "storage.googleapis.com" in url:
                LOGGER.warning("Direct GCS download failed, retrying via proxy: %s", exc)
                proxy_url = f"{self._GCS_PROXY}{quote(url, safe='')}"
                if part_path.exists():
                    part_path.unlink()
                try:
                    self._download_with_retries(
                        proxy_url,
                        part_path,
                        target,
                        attempts,
                        progress_callback,
                        pause_event,
                        cancel_event,
                        timeout,
                    )
                except requests.RequestException as exc2:
                    LOGGER.exception("Proxy download also failed")
                    raise AgnesAPIError(f"下载失败（含代理）：{exc2}") from exc2
            else:
                LOGGER.exception("Download failed")
                raise AgnesAPIError(f"下载失败：{exc}") from exc

        if progress_callback:
            size = target.stat().st_size if target.exists() else 0
            progress_callback(100, size, size)
        LOGGER.info("Download completed %s -> %s", url, target)
        return target

    def _download_with_retries(
        self,
        url: str,
        part_path: Path,
        target: Path,
        attempts: int,
        progress_callback: ProgressCallback | None,
        pause_event: threading.Event | None,
        cancel_event: threading.Event | None,
        timeout: int,
    ) -> None:
        last_error: requests.RequestException | None = None
        for attempt in range(1, attempts + 1):
            downloaded = part_path.stat().st_size if part_path.exists() else 0
            headers = {"Range": f"bytes={downloaded}-"} if downloaded else {}
            try:
                self._do_download(
                    url,
                    part_path,
                    target,
                    headers,
                    downloaded,
                    progress_callback,
                    pause_event,
                    cancel_event,
                    timeout,
                )
                return
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts or not self._is_retryable(exc):
                    break
                wait_seconds = min(2 ** (attempt - 1), self.MAX_BACKOFF_SECONDS)
                LOGGER.warning(
                    "Download interrupted (attempt %d/%d, resume=%d bytes), retrying in %ss: %s",
                    attempt,
                    attempts,
                    downloaded,
                    wait_seconds,
                    exc,
                )
                self._reset_session()
                time.sleep(wait_seconds)

        if last_error is None:
            raise requests.RequestException("Download failed without a captured error.")
        raise last_error

    def _do_download(
        self,
        url: str,
        part_path: Path,
        target: Path,
        headers: dict[str, str],
        downloaded: int,
        progress_callback: ProgressCallback | None,
        pause_event: threading.Event | None,
        cancel_event: threading.Event | None,
        timeout: int,
    ) -> None:
        with self._session.get(url, stream=True, headers=headers, timeout=timeout) as response:
            if response.status_code == 416:
                part_path.replace(target)
                return
            response.raise_for_status()

            can_resume = bool(downloaded and response.status_code == 206)
            if downloaded and not can_resume:
                downloaded = 0
            total = self._total_size(response, downloaded)
            mode = "ab" if can_resume else "wb"

            with part_path.open(mode) as fh:
                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if cancel_event and cancel_event.is_set():
                        LOGGER.info("Download cancelled %s", url)
                        raise AgnesAPIError("下载已取消。")
                    if pause_event and pause_event.is_set():
                        LOGGER.info("Download paused %s", url)
                        raise AgnesAPIError("下载已暂停。")
                    if chunk:
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress = int(downloaded * 100 / total) if total else 0
                            progress_callback(progress, downloaded, total)

        os.replace(part_path, target)

    def _reset_session(self) -> None:
        try:
            self._session.close()
        finally:
            self._session = requests.Session()

    @classmethod
    def _is_retryable(cls, exc: requests.RequestException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout, ChunkedEncodingError)):
            return True
        response = getattr(exc, "response", None)
        return bool(response is not None and response.status_code in cls.RETRYABLE_STATUS_CODES)

    @staticmethod
    def _total_size(response: requests.Response, downloaded: int) -> int:
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            total_part = content_range.rsplit("/", 1)[-1]
            if total_part.isdigit():
                return int(total_part)
        length = response.headers.get("Content-Length")
        if length and length.isdigit():
            return int(length) + downloaded
        return 0
