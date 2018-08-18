from __future__ import annotations

import base64
import mimetypes
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from api.client import AgnesAPIError, AgnesClient
from utils.logging_utils import LOGGER


def _create_retry_session(max_retries: int = 3) -> requests.Session:
    """Create a requests session with automatic retry on transient errors."""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=4, pool_maxsize=4)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


@dataclass
class VideoTask:
    task_id: str
    status: str = "queued"
    progress: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    completed_at: str = ""
    video_url: str = ""
    error: str = ""
    raw: dict[str, Any] | None = None


class VideoGenerator:
    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    def create_task(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        model: str = "agnes-video-v2.0",
        mode: str = "text",
        resolution: str = "1152x768",
        fps: int = 24,
        duration_seconds: int = 5,
        image_path: str = "",
    ) -> VideoTask:
        width, height = self._parse_resolution(resolution)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "height": height,
            "width": width,
            "frame_rate": int(fps),
            "num_frames": self._frames_for_duration(duration_seconds, fps),
        }
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if mode == "image":
            if not image_path:
                raise AgnesAPIError("图生视频模式需要先上传图片。")
            data_uri = self._image_payload(image_path)
            # Agnes video API expects raw base64 (no data URI prefix)
            if "," in data_uri:
                payload["image"] = data_uri.split(",", 1)[1]
            else:
                payload["image"] = data_uri

        data = self.client.request("POST", "/videos", json_payload=payload, timeout=180)
        task_id = (
            data.get("id")
            or data.get("task_id")
            or data.get("video_id")
            or data.get("data", {}).get("id")
            or data.get("data", {}).get("task_id")
        )
        if not task_id:
            raise AgnesAPIError("视频任务创建成功但响应中没有 task_id。", raw=data)

        status = data.get("status") or data.get("data", {}).get("status") or "queued"
        created_at = data.get("created_at") or datetime.now().isoformat(timespec="seconds")
        return VideoTask(
            task_id=str(task_id),
            status=str(status),
            progress=self._parse_progress(data),
            created_at=str(created_at),
            raw=data,
        )

    def query_task(self, task_id: str) -> VideoTask:
        # Retry on transient errors (502, 503, timeout, connection reset)
        data = None
        for attempt in range(3):
            try:
                data = self.client.request("GET", f"/videos/{task_id}", timeout=90)
                break
            except Exception as exc:
                LOGGER.warning("Video query attempt %d/3 failed for %s: %s", attempt + 1, task_id, exc)
                if attempt < 2:
                    import time as _t; _t.sleep((attempt + 1) * 2)
                else:
                    raise AgnesAPIError(f"查询视频任务失败（重试 {attempt + 1} 次）：{exc}") from exc
        if data is None:
            raise AgnesAPIError("查询视频任务失败：所有重试均失败")
        payload = data.get("data", data) if isinstance(data, dict) else {}
        status = str(payload.get("status") or payload.get("state") or "queued")

        # Try to find video URL from payload first, then from raw data
        video_url = self._parse_video_url(payload)
        if not video_url and isinstance(data, dict) and data is not payload:
            video_url = self._parse_video_url(data)

        # Log raw response if task is completed but no URL found (for debugging)
        if status.lower() in ("completed", "succeeded", "success", "finished") and not video_url:
            LOGGER.warning(
                "Task %s is completed but no video URL found. Raw response keys: %s",
                task_id,
                list(data.keys()) if isinstance(data, dict) else "not a dict",
            )
            LOGGER.warning("Raw response: %s", str(data)[:2000])

        return VideoTask(
            task_id=str(payload.get("id") or payload.get("task_id") or task_id),
            status=status,
            progress=self._parse_progress(payload),
            created_at=str(payload.get("created_at") or ""),
            completed_at=str(payload.get("completed_at") or payload.get("finished_at") or ""),
            video_url=video_url,
            error=str(payload.get("error") or payload.get("failure_reason") or ""),
            raw=data,
        )

    _GCS_PROXY = "https://api.codetabs.com/v1/proxy?quest="

    def download_video(self, url: str, target_path: str | Path, *, timeout: int = 600) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._do_download(url, target, timeout)
        except requests.RequestException as exc:
            if "storage.googleapis.com" in url:
                LOGGER.warning("Direct GCS download failed, retrying via proxy: %s", exc)
                proxy_url = f"{self._GCS_PROXY}{quote(url, safe='')}"
                try:
                    self._do_download(proxy_url, target, timeout)
                    LOGGER.info("Downloaded video (via proxy) %s -> %s", url, target)
                    return target
                except requests.RequestException as exc2:
                    LOGGER.exception("Proxy video download also failed")
                    raise AgnesAPIError(f"视频下载失败（含代理）：{exc2}") from exc2
            LOGGER.exception("Video download failed")
            raise AgnesAPIError(f"视频下载失败：{exc}") from exc
        LOGGER.info("Downloaded video %s -> %s", url, target)
        return target

    @staticmethod
    def _do_download(url: str, target: Path, timeout: int) -> None:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with target.open("wb") as fh:
                shutil.copyfileobj(response.raw, fh)

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, int]:
        left, right = resolution.lower().split("x", 1)
        return int(left), int(right)

    @staticmethod
    def _frames_for_duration(duration_seconds: int, fps: int) -> int:
        frames = int(duration_seconds) * int(fps) + 1
        remainder = (frames - 1) % 8
        if remainder:
            frames += 8 - remainder
        return min(frames, 441)

    @staticmethod
    def _image_payload(image_path: str) -> str:
        # Already a data URI (from web upload)
        if image_path.startswith("data:"):
            # Parse the data URI
            try:
                header, b64_data = image_path.split(",", 1)
            except ValueError:
                raise AgnesAPIError("上传图片格式无效（data URI 缺少逗号分隔符）。")

            # Strip whitespace that may have been introduced during transport
            b64_data = b64_data.strip()

            # Remove any existing padding before validation
            b64_data = b64_data.rstrip("=")

            # Handle invalid base64 length: len % 4 == 1 means data is
            # corrupted (3 chars lost in transport).  Truncate 1 char
            # so len % 4 == 0, which at least gives us valid base64.
            remainder = len(b64_data) % 4
            if remainder == 1:
                LOGGER.warning(
                    "Base64 data length %d has remainder 1 (corrupted in transport). "
                    "Truncating 1 character to recover valid base64.",
                    len(b64_data),
                )
                b64_data = b64_data[:-1]

            # Re-pad to a multiple of 4
            pad_needed = len(b64_data) % 4
            if pad_needed:
                b64_data += "=" * (4 - pad_needed)

            # Decode → validate → re-encode to guarantee valid base64
            try:
                raw_bytes = base64.b64decode(b64_data)
            except Exception as exc:
                raise AgnesAPIError(
                    f"上传图片 base64 数据无效，可能在传输中损坏"
                    f"（长度={len(b64_data)}，余数={len(b64_data) % 4}）：{exc}"
                )

            # Re-encode from raw bytes — this is the key step that
            # guarantees the output base64 is always valid and properly padded
            b64_clean = base64.b64encode(raw_bytes).decode("ascii")
            LOGGER.info(
                "Image base64 validated and re-encoded: %d bytes → %d b64 chars",
                len(raw_bytes), len(b64_clean),
            )
            return f"{header},{b64_clean}"

        if image_path.startswith(("http://", "https://")):
            # Download remote image and convert to base64 data URI
            LOGGER.info("Downloading remote image for base64 encoding: %s", image_path[:120])
            try:
                resp = requests.get(image_path, timeout=60)
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise AgnesAPIError(f"下载远程图片失败：{exc}") from exc

            content_type = resp.headers.get("Content-Type", "image/png")
            # Normalize content type
            if "jpeg" in content_type or "jpg" in content_type:
                mime_type = "image/jpeg"
            elif "png" in content_type:
                mime_type = "image/png"
            elif "webp" in content_type:
                mime_type = "image/webp"
            else:
                mime_type = content_type.split(";")[0].strip() or "image/png"

            encoded = base64.b64encode(resp.content).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"

        path = Path(image_path)
        if not path.exists():
            raise AgnesAPIError("上传图片不存在，请重新选择。")

        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _parse_progress(payload: dict[str, Any]) -> int:
        progress = payload.get("progress") or payload.get("percent") or payload.get("progress_percent")
        if progress is None:
            status = str(payload.get("status", "")).lower()
            if status == "completed":
                return 100
            if status == "failed":
                return 0
            return 0
        try:
            value = float(progress)
            if value <= 1:
                value *= 100
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_video_url(payload: dict[str, Any]) -> str:
        # Direct field candidates
        url_keys = {
            "video_url", "url", "result_url", "download_url",
            "video_download_url", "file_url", "media_url",
            "src", "source", "link", "href",
            "remixed_from_video_id", "video_id", "output_url",
        }
        candidates: list[str] = []

        for key in url_keys:
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())

        # Check nested dict fields
        nested_keys = {"video", "output", "result", "data", "file", "media", "task", "response"}
        for nk in nested_keys:
            nested = payload.get(nk)
            if isinstance(nested, dict):
                for key in url_keys:
                    val = nested.get(key)
                    if isinstance(val, str) and val.strip():
                        candidates.append(val.strip())
                # Go one more level deep
                for sub_key, sub_val in nested.items():
                    if isinstance(sub_val, dict):
                        for key in url_keys:
                            val = sub_val.get(key)
                            if isinstance(val, str) and val.strip():
                                candidates.append(val.strip())
            elif isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        for key in url_keys:
                            val = item.get(key)
                            if isinstance(val, str) and val.strip():
                                candidates.append(val.strip())
                    elif isinstance(item, str) and ("http" in item or "://" in item):
                        candidates.append(item.strip())

        # Filter: prefer URLs that look like video files
        video_extensions = (".mp4", ".mov", ".webm", ".avi", ".mkv")
        video_urls = [u for u in candidates if any(u.lower().endswith(ext) for ext in video_extensions)]
        if video_urls:
            return video_urls[0]

        # Then prefer http(s) URLs
        http_urls = [u for u in candidates if u.startswith("http://") or u.startswith("https://")]
        if http_urls:
            return http_urls[0]

        # Return any candidate
        return candidates[0] if candidates else ""
