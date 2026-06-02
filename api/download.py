from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

from api.client import AgnesAPIError
from utils.logging_utils import LOGGER


ProgressCallback = Callable[[int, int, int], None]


class DownloadManagerBackend:
    """Optimized download backend with larger chunks and connection reuse."""

    # 1MB chunks for faster downloads (was 256KB)
    CHUNK_SIZE = 1024 * 1024

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
    ) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_path = target.with_suffix(target.suffix + ".part")
        headers: dict[str, str] = {}
        downloaded = part_path.stat().st_size if part_path.exists() else 0
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"

        try:
            self._do_download(url, part_path, target, headers, downloaded,
                              progress_callback, pause_event, cancel_event, timeout)
        except requests.RequestException as exc:
            # Retry Google Cloud Storage via proxy if direct download fails
            if "storage.googleapis.com" in url:
                LOGGER.warning("Direct GCS download failed, retrying via proxy: %s", exc)
                proxy_url = f"{self._GCS_PROXY}{quote(url, safe='')}"
                try:
                    headers_proxy: dict[str, str] = {}
                    downloaded_proxy = 0
                    self._do_download(proxy_url, part_path, target, headers_proxy,
                                      downloaded_proxy, progress_callback,
                                      pause_event, cancel_event, timeout)
                    return target
                except requests.RequestException as exc2:
                    LOGGER.exception("Proxy download also failed")
                    raise AgnesAPIError(f"下载失败（含代理）：{exc2}") from exc2
            LOGGER.exception("Download failed")
            raise AgnesAPIError(f"下载失败：{exc}") from exc

        if progress_callback:
            size = target.stat().st_size if target.exists() else downloaded
            progress_callback(100, size, size)
        LOGGER.info("Download completed %s -> %s", url, target)
        return target

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

            total = self._total_size(response, downloaded)
            mode = "ab" if downloaded and response.status_code == 206 else "wb"
            if mode == "wb":
                downloaded = 0

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
