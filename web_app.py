"""Agnes AI Client — Web Backend (FastAPI)"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── existing modules ──
from api.client import AgnesClient, AgnesAPIError
from api.chat_api import ChatGenerator
from api.image_api import ImageGenerator
from api.video_api import VideoGenerator
from api.download import DownloadManagerBackend
from config.app_config import AppConfig
from database.history_db import HistoryDatabase
from utils.path_utils import (
    DOWNLOADS_DIR, IMAGE_HISTORY_DIR, VIDEO_HISTORY_DIR,
    ensure_directories, safe_filename,
)
from utils.logging_utils import LOGGER

# ── App ──
app = FastAPI(title="Agnes AI Client", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_directories()
db = HistoryDatabase()
config = AppConfig.load()

# active video tasks for polling
_active_video_tasks: dict[str, dict] = {}
_poll_lock = threading.Lock()

# Track poll counts and last-known status per task (for timeout detection)
_task_poll_meta: dict[str, dict] = {}  # {task_id: {"polls": int, "first_seen": float, "last_status": str}}

# Track which completed/failed tasks have already been notified (prevent duplicate toasts)
_notified_tasks: set[str] = set()

# Timeout thresholds (seconds)
_QUEUED_TIMEOUT = 600       # 10 minutes stuck in queued → likely rejected
_IN_PROGRESS_TIMEOUT = 900   # 15 minutes stuck in_progress with no progress change

# download manager
_download_manager = DownloadManagerBackend()

# ── Shared HTTP client (connection pool reuse) ──
_shared_client: AgnesClient | None = None
_shared_client_lock = threading.Lock()

def _get_shared_client() -> AgnesClient:
    """Return a module-level shared AgnesClient with a persistent HTTP session (connection reuse)."""
    global _shared_client
    with _shared_client_lock:
        if _shared_client is None or not config.api_key:
            if not config.api_key:
                raise HTTPException(400, "请先配置 API Key")
            _shared_client = AgnesClient(api_key=config.api_key, base_url=config.base_url)
        elif _shared_client.api_key != config.api_key or _shared_client.base_url != config.base_url:
            _shared_client = AgnesClient(api_key=config.api_key, base_url=config.base_url)
        return _shared_client

# ── Thread pool for parallel polling ──
_poll_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="video-poll")

# ── WebSocket connection manager for push notifications ──
_ws_connections: set[WebSocket] = set()
_ws_lock = asyncio.Lock()

async def _ws_broadcast(message: dict):
    """Broadcast a JSON message to all connected WebSocket clients."""
    async with _ws_lock:
        dead: list[WebSocket] = []
        for ws in _ws_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_connections.discard(ws)


# ─────────────── Pydantic Models ───────────────

class ConfigModel(BaseModel):
    api_key: str = ""
    base_url: str = "https://apihub.agnes-ai.com/v1"

class ImageGenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    model: str = "agnes-image-2.1-flash"
    size: str = "1024x1024"
    count: int = 1
    seed: str = ""

class VideoCreateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    model: str = "agnes-video-v2.0"
    mode: str = "text"
    resolution: str = "1152x768"
    fps: int = 24
    duration_seconds: int = 5
    image_base64: str = ""

class DownloadRequest(BaseModel):
    url: str
    file_name: str = ""
    save_path: str = ""

class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    model: str = "agnes-2.0-flash"
    temperature: float = 0.7
    top_p: float | None = None
    max_tokens: int = 4096
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    use_tools: bool = False


class ChatSaveRequest(BaseModel):
    conversation_id: int | None = None
    title: str = ""
    messages: list[dict[str, Any]]
    model: str = "agnes-2.0-flash"


# ── Tool Definitions for Agnes-2.0-Flash ──

_CREATIVE_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image using AI. Call this when the user wants to create, draw, or generate a picture/image/photo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed image description in English, including subject, scene, lighting, style, composition, and quality keywords."
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Things to avoid in the image, e.g. 'blurry, deformed, watermark, low quality'."
                    },
                    "size": {
                        "type": "string",
                        "enum": ["1024x1024", "1024x1536", "1536x1024"],
                        "description": "Image dimensions. Default 1024x1024."
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": "Generate a video using AI. Call this when the user wants to create, produce, or generate a video/animation/clip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed video description in English, including subject motion, camera movement, scene transitions, lighting, atmosphere, and duration hints."
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Things to avoid in the video, e.g. 'morphing, jitter, watermark, low quality'."
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["1152x768", "768x1152"],
                        "description": "Video resolution. 1152x768 for landscape, 768x1152 for portrait. Default 1152x768."
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "enum": [5, 8, 10],
                        "description": "Video duration in seconds. Default 5."
                    }
                },
                "required": ["prompt"]
            }
        }
    }
]


# ─────────────── Helpers ───────────────

def _get_client() -> AgnesClient:
    if not config.api_key:
        raise HTTPException(400, "请先配置 API Key")
    return _get_shared_client()


# ─────────────── Config ───────────────

@app.get("/api/config")
def get_config():
    return {
        "api_key": config.api_key,
        "base_url": config.base_url,
    }

@app.post("/api/config")
def save_config(body: ConfigModel):
    config.api_key = body.api_key.strip()
    config.base_url = body.base_url.strip() or "https://apihub.agnes-ai.com/v1"
    config.save()
    return {"ok": True}


# ─────────────── Image Generation ───────────────

@app.post("/api/image/generate")
def generate_images(body: ImageGenerateRequest):
    if not body.prompt.strip():
        raise HTTPException(400, "请输入 Prompt")
    client = _get_client()
    gen = ImageGenerator(client)

    results: list[dict] = []
    try:
        image_results = gen.generate(
            prompt=body.prompt.strip(),
            negative_prompt=body.negative_prompt.strip(),
            model=body.model,
            size=body.size,
            count=body.count,
            seed=int(body.seed) if body.seed.strip() else None,
        )
        # download images
        local_paths: list[str] = []
        result_urls: list[str] = []
        for i, img in enumerate(image_results):
            url = img.url or ""
            result_urls.append(url)
            if url:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                prompt_short = safe_filename(body.prompt[:30])
                fname = f"{ts}_{prompt_short}_{i+1}.png"
                local = str(IMAGE_HISTORY_DIR / fname)
                try:
                    gen.download_image(url, local)
                    local_paths.append(local)
                except Exception as e:
                    LOGGER.warning("Image download failed: %s", e)
                    local_paths.append("")
            else:
                local_paths.append("")

        # save to history
        db.insert_image_history(
            prompt=body.prompt.strip(),
            negative_prompt=body.negative_prompt.strip(),
            model=body.model,
            size=body.size,
            count=body.count,
            seed=body.seed,
            result_urls=result_urls,
            local_paths=local_paths,
        )

        for url, lp in zip(result_urls, local_paths):
            results.append({"url": url, "local_path": lp})
    except AgnesAPIError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        LOGGER.exception("Image generation failed")
        raise HTTPException(500, f"图片生成失败：{exc}")

    return {"images": results}


@app.get("/api/image/history")
def get_image_history():
    """Return all generated images from history for image picker."""
    images: list[dict] = []
    rows = db.search_history("")
    for r in rows:
        if r.get("kind") != "image":
            continue
        local_paths_raw = r.get("local_path", "")
        urls_raw = r.get("result_url", "")
        local_paths = [p.strip() for p in local_paths_raw.split(",") if p.strip()]
        urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
        for i, lp in enumerate(local_paths):
            if Path(lp).exists():
                images.append({
                    "local_path": lp,
                    "url": urls[i] if i < len(urls) else "",
                    "prompt": r.get("prompt", ""),
                    "created_at": r.get("created_at", ""),
                })
        # Also include URL-only images if no local path
        if not local_paths:
            for u in urls:
                images.append({
                    "local_path": "",
                    "url": u,
                    "prompt": r.get("prompt", ""),
                    "created_at": r.get("created_at", ""),
                })
    return {"images": images}


# ─────────────── Video Generation ───────────────

@app.post("/api/video/create")
def create_video_task(body: VideoCreateRequest):
    if not body.prompt.strip():
        raise HTTPException(400, "请输入 Prompt")
    client = _get_client()
    gen = VideoGenerator(client)
    try:
        task = gen.create_task(
            prompt=body.prompt.strip(),
            negative_prompt=body.negative_prompt.strip(),
            model=body.model,
            mode=body.mode,
            resolution=body.resolution,
            fps=body.fps,
            duration_seconds=body.duration_seconds,
            image_path=body.image_base64 if body.mode == "image" else "",
        )
        record = {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at,
            "prompt": body.prompt.strip(),
            "negative_prompt": body.negative_prompt.strip(),
            "model": body.model,
            "mode": body.mode,
            "resolution": body.resolution,
            "duration_seconds": body.duration_seconds,
            "fps": body.fps,
            "result_url": "",
            "completed_at": "",
            "error": "",
        }
        db.insert_video_task(
            task_id=task.task_id,
            prompt=body.prompt.strip(),
            negative_prompt=body.negative_prompt.strip(),
            model=body.model,
            mode=body.mode,
            resolution=body.resolution,
            duration_seconds=body.duration_seconds,
            fps=body.fps,
            status=task.status,
            progress=task.progress,
            created_at=task.created_at,
            source_image_path=body.image_base64[:100] if body.mode == "image" else "",
        )
        with _poll_lock:
            _active_video_tasks[task.task_id] = record
            _task_poll_meta[task.task_id] = {
                "polls": 0,
                "first_seen": time.time(),
                "last_status": task.status,
                "last_progress": task.progress,
                "last_progress_change": time.time(),
            }
        return record
    except AgnesAPIError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        LOGGER.exception("Video creation failed")
        raise HTTPException(500, f"视频任务创建失败：{exc}")


@app.get("/api/video/tasks")
def get_video_tasks():
    """Return all video tasks (active ones get polled first)."""
    tasks = db.list_video_tasks(active_only=False)
    # Also include active tasks from memory
    with _poll_lock:
        for tid, rec in _active_video_tasks.items():
            found = False
            for t in tasks:
                if t.get("task_id") == tid:
                    found = True
                    break
            if not found:
                tasks.insert(0, rec)
    return {"tasks": tasks}


@app.get("/api/video/poll/{task_id}")
def poll_video_task(task_id: str):
    """Poll a single video task from API."""
    client = _get_client()
    gen = VideoGenerator(client)
    try:
        task = gen.query_task(task_id)
        status = task.status.lower()
        if status in ("succeeded", "success", "finished", "done"):
            status = "completed"
        elif status in ("running", "processing", "pending"):
            status = "in_progress"
        elif status in ("error", "cancelled", "canceled"):
            status = "failed"

        result_url = task.video_url or ""
        completed_at = task.completed_at or (
            datetime.now().isoformat(timespec="seconds")
            if status in ("completed", "failed") else ""
        )
        progress = task.progress or (100 if status == "completed" else 0)

        db.update_video_task(
            task_id=task_id,
            status=status,
            progress=progress,
            result_url=result_url,
            completed_at=completed_at,
            error=task.error or "",
        )

        with _poll_lock:
            if status in ("completed", "failed"):
                _active_video_tasks.pop(task_id, None)
                _task_poll_meta.pop(task_id, None)
            elif task_id in _active_video_tasks:
                _active_video_tasks[task_id]["status"] = status
                _active_video_tasks[task_id]["progress"] = progress
                _active_video_tasks[task_id]["result_url"] = result_url

        return {
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "video_url": result_url,
            "completed_at": completed_at,
            "error": task.error or "",
        }
    except AgnesAPIError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/video/cancel/{task_id}")
def cancel_video_task(task_id: str):
    """Manually cancel a stuck video task."""
    LOGGER.info("User cancelled task %s", task_id)
    db.update_video_task(
        task_id=task_id,
        status="failed",
        error="用户手动取消",
        completed_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _poll_lock:
        _active_video_tasks.pop(task_id, None)
        _task_poll_meta.pop(task_id, None)
    _notified_tasks.discard(task_id)
    return {"ok": True, "task_id": task_id}


def _poll_single_task(task_id: str, gen: VideoGenerator, now: float) -> dict:
    """Poll a single video task. Called from the thread pool for parallel execution."""
    # ── Timeout detection ──
    with _poll_lock:
        meta = _task_poll_meta.get(task_id)
    if meta:
        with _poll_lock:
            meta["polls"] += 1
        elapsed = now - meta["first_seen"]
        stuck_in_queued = (
            meta["last_status"] in ("queued",)
            and elapsed > _QUEUED_TIMEOUT
        )
        stuck_in_progress = (
            meta["last_status"] in ("in_progress", "processing", "running")
            and (now - meta.get("last_progress_change", meta["first_seen"])) > _IN_PROGRESS_TIMEOUT
        )
        if stuck_in_queued or stuck_in_progress:
            reason = "任务在队列中等待超时，可能已被服务端拒绝" if stuck_in_queued else "任务处理超时，可能已异常终止"
            LOGGER.warning("Task %s timed out after %ds (status=%s, polls=%d)", task_id, elapsed, meta["last_status"], meta["polls"])
            db.update_video_task(
                task_id=task_id,
                status="failed",
                progress=meta.get("last_progress", 0),
                error=reason,
                completed_at=datetime.now().isoformat(timespec="seconds"),
            )
            with _poll_lock:
                _active_video_tasks.pop(task_id, None)
                _task_poll_meta.pop(task_id, None)
            return {
                "task_id": task_id,
                "status": "failed",
                "progress": meta.get("last_progress", 0),
                "video_url": "",
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "error": reason,
                "newly_completed": False,
                "newly_failed": True,
            }

    # ── Normal API poll ──
    try:
        task = gen.query_task(task_id)
        status = task.status.lower()
        if status in ("succeeded", "success", "finished", "done"):
            status = "completed"
        elif status in ("running", "processing", "pending"):
            status = "in_progress"
        elif status in ("error", "cancelled", "canceled"):
            status = "failed"

        result_url = task.video_url or ""
        completed_at = task.completed_at or (
            datetime.now().isoformat(timespec="seconds")
            if status in ("completed", "failed") else ""
        )
        progress = task.progress or (100 if status == "completed" else 0)

        # ── Track progress changes for timeout detection ──
        if meta:
            with _poll_lock:
                if progress != meta.get("last_progress"):
                    meta["last_progress"] = progress
                    meta["last_progress_change"] = now
                meta["last_status"] = status

        db.update_video_task(
            task_id=task_id,
            status=status,
            progress=progress,
            result_url=result_url,
            completed_at=completed_at,
            error=task.error or "",
        )

        # ── Determine if this is a NEW completion/failure (for toast dedup) ──
        newly_completed = False
        newly_failed = False
        if status in ("completed", "failed"):
            if task_id not in _notified_tasks:
                _notified_tasks.add(task_id)
                if status == "completed":
                    newly_completed = True
                else:
                    newly_failed = True
            with _poll_lock:
                _active_video_tasks.pop(task_id, None)
                _task_poll_meta.pop(task_id, None)
        elif task_id in _active_video_tasks:
            with _poll_lock:
                _active_video_tasks[task_id]["status"] = status
                _active_video_tasks[task_id]["progress"] = progress

        return {
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "video_url": result_url,
            "completed_at": completed_at,
            "error": task.error or "",
            "newly_completed": newly_completed,
            "newly_failed": newly_failed,
        }
    except Exception as exc:
        LOGGER.warning("Poll failed for %s: %s", task_id, exc)
        return {
            "task_id": task_id,
            "status": "poll_error",
            "progress": 0,
            "video_url": "",
            "completed_at": "",
            "error": f"轮询出错: {exc}",
            "newly_completed": False,
            "newly_failed": False,
        }


@app.get("/api/video/poll-all")
def poll_all_active():
    """Poll all active tasks in PARALLEL, with timeout detection. Also returns full task list."""
    with _poll_lock:
        task_ids = list(_active_video_tasks.keys())

    # Also check DB for active tasks not yet in memory
    db_tasks = db.list_video_tasks(active_only=True)
    for t in db_tasks:
        tid = t.get("task_id", "")
        if tid and tid not in task_ids:
            task_ids.append(tid)
            with _poll_lock:
                if tid not in _task_poll_meta:
                    _task_poll_meta[tid] = {
                        "polls": 0,
                        "first_seen": time.time(),
                        "last_status": t.get("status", "queued"),
                        "last_progress": t.get("progress", 0),
                        "last_progress_change": time.time(),
                    }

    if not task_ids:
        # No active tasks — return empty results + full task list
        all_tasks = db.list_video_tasks(active_only=False)
        return {"results": [], "tasks": all_tasks}

    client = _get_client()
    gen = VideoGenerator(client)
    now = time.time()

    # ── Parallel polling via ThreadPoolExecutor ──
    results: list[dict] = []
    futures = {
        _poll_executor.submit(_poll_single_task, tid, gen, now): tid
        for tid in task_ids
    }
    for future in as_completed(futures):
        try:
            result = future.result()
            results.append(result)
        except Exception as exc:
            tid = futures[future]
            LOGGER.warning("Parallel poll crashed for %s: %s", tid, exc)
            results.append({
                "task_id": tid, "status": "poll_error", "progress": 0,
                "video_url": "", "completed_at": "", "error": str(exc),
                "newly_completed": False, "newly_failed": False,
            })

    # ── Return full task list (merged response, frontend no longer needs separate call) ──
    all_tasks = db.list_video_tasks(active_only=False)
    # Also include active in-memory tasks not yet in DB
    with _poll_lock:
        for tid, rec in _active_video_tasks.items():
            if not any(t.get("task_id") == tid for t in all_tasks):
                all_tasks.insert(0, rec)

    return {"results": results, "tasks": all_tasks}


def _schedule_ws_broadcast(results: list[dict]):
    """Fire-and-forget WebSocket broadcast for newly completed/failed tasks."""
    events = []
    for r in results:
        if r.get("newly_completed"):
            events.append({"type": "task_completed", "task_id": r["task_id"], "video_url": r.get("video_url", "")})
        if r.get("newly_failed"):
            events.append({"type": "task_failed", "task_id": r["task_id"], "error": r.get("error", "")})
    if not events:
        return
    try:
        loop = asyncio.get_event_loop()
        for event in events:
            loop.create_task(_ws_broadcast(event))
    except RuntimeError:
        pass  # No event loop available (sync context without running loop)


@app.get("/api/video/poll-all-async")
async def poll_all_active_async():
    """Async version of poll-all that also broadcasts WebSocket events."""
    # Run the sync poll in a thread to avoid blocking
    import asyncio as aio
    result = await aio.get_event_loop().run_in_executor(_poll_executor, _sync_poll_all)
    # Broadcast WebSocket events
    for r in result.get("results", []):
        if r.get("newly_completed"):
            await _ws_broadcast({"type": "task_completed", "task_id": r["task_id"], "video_url": r.get("video_url", "")})
        if r.get("newly_failed"):
            await _ws_broadcast({"type": "task_failed", "task_id": r["task_id"], "error": r.get("error", "")})
    return result


def _sync_poll_all() -> dict:
    """Extracted sync polling logic for use by both sync and async endpoints."""
    with _poll_lock:
        task_ids = list(_active_video_tasks.keys())

    db_tasks = db.list_video_tasks(active_only=True)
    for t in db_tasks:
        tid = t.get("task_id", "")
        if tid and tid not in task_ids:
            task_ids.append(tid)
            with _poll_lock:
                if tid not in _task_poll_meta:
                    _task_poll_meta[tid] = {
                        "polls": 0,
                        "first_seen": time.time(),
                        "last_status": t.get("status", "queued"),
                        "last_progress": t.get("progress", 0),
                        "last_progress_change": time.time(),
                    }

    if not task_ids:
        all_tasks = db.list_video_tasks(active_only=False)
        return {"results": [], "tasks": all_tasks}

    client = _get_client()
    gen = VideoGenerator(client)
    now = time.time()

    results: list[dict] = []
    futures = {
        _poll_executor.submit(_poll_single_task, tid, gen, now): tid
        for tid in task_ids
    }
    for future in as_completed(futures):
        try:
            result = future.result()
            results.append(result)
        except Exception as exc:
            tid = futures[future]
            results.append({
                "task_id": tid, "status": "poll_error", "progress": 0,
                "video_url": "", "completed_at": "", "error": str(exc),
                "newly_completed": False, "newly_failed": False,
            })

    all_tasks = db.list_video_tasks(active_only=False)
    with _poll_lock:
        for tid, rec in _active_video_tasks.items():
            if not any(t.get("task_id") == tid for t in all_tasks):
                all_tasks.insert(0, rec)

    return {"results": results, "tasks": all_tasks}


# ── Video Stream Proxy (解决 GCS 在国内被屏蔽的问题) ──
from urllib.parse import quote as _url_quote

_GCS_PROXY_PREFIX = "https://api.codetabs.com/v1/proxy?quest="

def _stream_url_with_gcs_fallback(url: str):
    """Generator that streams a URL's content, with GCS proxy fallback."""
    import requests as _req
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with _req.get(url, stream=True, timeout=60, headers=headers) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    yield chunk
    except Exception:
        if "storage.googleapis.com" in url:
            proxy_url = f"{_GCS_PROXY_PREFIX}{_url_quote(url, safe='')}"
            LOGGER.info("Video stream: retrying GCS via proxy")
            with _req.get(proxy_url, stream=True, timeout=120, headers=headers) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        yield chunk
        else:
            raise


@app.get("/api/video/stream/{task_id}")
def stream_video(task_id: str):
    """Stream video content through server (GCS proxy fallback)."""
    # Look up the task's video URL from DB
    tasks = db.list_video_tasks(active_only=False)
    video_url = ""
    for t in tasks:
        if t.get("task_id") == task_id:
            video_url = t.get("result_url", "")
            break
    if not video_url:
        # Also check active in-memory tasks
        with _poll_lock:
            rec = _active_video_tasks.get(task_id)
            if rec:
                video_url = rec.get("result_url", "")
    if not video_url:
        raise HTTPException(404, "未找到视频 URL")

    return StreamingResponse(
        _stream_url_with_gcs_fallback(video_url),
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ─────────────── Downloads ───────────────

# ── Background download worker ──
_dl_worker_thread: threading.Thread | None = None
_dl_worker_stop = threading.Event()

def _download_worker_loop():
    """Background thread that processes queued download records."""
    LOGGER.info("Download worker started")
    while not _dl_worker_stop.is_set():
        try:
            downloads = db.list_downloads()
            queued = [d for d in downloads if d.get("status") == "queued"]
            for dl in queued:
                if _dl_worker_stop.is_set():
                    break
                dl_id = dl.get("id")
                url = dl.get("url", "")
                save_path = dl.get("save_path", "")
                if not url or not save_path:
                    continue
                db.update_download(dl_id, status="downloading")
                try:
                    def _progress_cb(progress, downloaded, total):
                        db.update_download(dl_id, progress=progress, size=total)

                    _download_manager.download_file(
                        url=url,
                        target_path=save_path,
                        progress_callback=_progress_cb,
                    )
                    file_size = Path(save_path).stat().st_size if Path(save_path).exists() else 0
                    db.update_download(dl_id, status="completed", progress=100, size=file_size)
                    LOGGER.info("Download completed: %s -> %s", url, save_path)
                except Exception as exc:
                    LOGGER.exception("Download failed: %s", url)
                    db.update_download(dl_id, status="failed")
        except Exception:
            LOGGER.exception("Download worker error")
        _dl_worker_stop.wait(timeout=3)
    LOGGER.info("Download worker stopped")

@app.on_event("startup")
def _start_download_worker():
    global _dl_worker_thread
    _dl_worker_stop.clear()
    _dl_worker_thread = threading.Thread(target=_download_worker_loop, daemon=True, name="dl-worker")
    _dl_worker_thread.start()

@app.on_event("shutdown")
def _stop_download_worker():
    _dl_worker_stop.set()

@app.post("/api/download")
def add_download(body: DownloadRequest):
    if not body.url:
        raise HTTPException(400, "缺少下载链接")
    file_name = body.file_name or safe_filename(body.url.split("/")[-1][:80]) or "download"
    save_path = body.save_path or str(DOWNLOADS_DIR / file_name)

    record = {
        "file_name": file_name,
        "file_type": "video" if any(e in body.url.lower() for e in (".mp4", ".mov", ".webm")) else "image",
        "size": 0,
        "progress": 0,
        "status": "queued",
        "save_path": save_path,
        "url": body.url,
    }
    db.add_download(
        file_name=record["file_name"],
        file_type=record["file_type"],
        save_path=record["save_path"],
        url=record["url"],
        status=record["status"],
    )
    return {"ok": True, "record": record}


@app.get("/api/downloads")
def get_downloads():
    return {"downloads": db.list_downloads()}


@app.delete("/api/download/{download_id}")
def delete_download(download_id: int):
    db.delete_download(download_id)
    return {"ok": True}


# ─────────────── Chat (Agnes-2.0-Flash) ───────────────

def _execute_tool_call(client: AgnesClient, name: str, arguments: dict) -> dict:
    """Execute a tool call and return the result for feeding back to the model."""
    try:
        if name == "generate_image":
            gen = ImageGenerator(client)
            results = gen.generate(
                prompt=arguments.get("prompt", ""),
                negative_prompt=arguments.get("negative_prompt", ""),
                size=arguments.get("size", "1024x1024"),
                count=1,
            )
            if results and results[0].url:
                url = results[0].url
                # Download to local for history
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                prompt_short = safe_filename(arguments.get("prompt", "img")[:30])
                local = str(IMAGE_HISTORY_DIR / f"{ts}_{prompt_short}.png")
                try:
                    gen.download_image(results[0], local)
                except Exception:
                    local = ""
                return {"success": True, "image_url": url, "local_path": local,
                        "message": f"Image generated successfully. URL: {url}"}
            return {"success": False, "message": "Image generation completed but no URL returned."}

        elif name == "generate_video":
            gen = VideoGenerator(client)
            task = gen.create_task(
                prompt=arguments.get("prompt", ""),
                negative_prompt=arguments.get("negative_prompt", ""),
                resolution=arguments.get("resolution", "1152x768"),
                duration_seconds=arguments.get("duration_seconds", 5),
            )
            # Register for background polling
            record = {
                "task_id": task.task_id,
                "status": task.status,
                "progress": task.progress,
                "created_at": task.created_at,
                "prompt": arguments.get("prompt", ""),
                "negative_prompt": arguments.get("negative_prompt", ""),
                "model": "agnes-video-v2.0",
                "mode": "text",
                "resolution": arguments.get("resolution", "1152x768"),
                "duration_seconds": arguments.get("duration_seconds", 5),
                "fps": 24,
                "result_url": "",
                "completed_at": "",
                "error": "",
            }
            db.insert_video_task(
                task_id=task.task_id,
                prompt=arguments.get("prompt", ""),
                negative_prompt=arguments.get("negative_prompt", ""),
                model="agnes-video-v2.0",
                mode="text",
                resolution=arguments.get("resolution", "1152x768"),
                duration_seconds=arguments.get("duration_seconds", 5),
                fps=24,
                status=task.status,
                progress=task.progress,
                created_at=task.created_at,
            )
            with _poll_lock:
                _active_video_tasks[task.task_id] = record
                _task_poll_meta[task.task_id] = {
                    "polls": 0,
                    "first_seen": time.time(),
                    "last_status": task.status,
                    "last_progress": task.progress,
                    "last_progress_change": time.time(),
                }
            return {"success": True, "task_id": task.task_id,
                    "message": f"Video generation task created (ID: {task.task_id}). "
                               f"The video is being generated and will be available when processing completes."}

        else:
            return {"success": False, "message": f"Unknown tool: {name}"}
    except AgnesAPIError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        LOGGER.exception("Tool execution failed for %s", name)
        return {"success": False, "message": f"Tool execution error: {exc}"}


@app.post("/api/chat/completions")
def chat_completions(body: ChatRequest):
    """Non-streaming chat completion endpoint."""
    if not body.messages:
        raise HTTPException(400, "消息列表不能为空")
    client = _get_client()
    gen = ChatGenerator(client)
    tools = body.tools
    tool_choice = body.tool_choice
    if body.use_tools and not tools:
        tools = _CREATIVE_TOOLS
        tool_choice = "auto"
    try:
        result = gen.complete(
            messages=body.messages,
            model=body.model,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        return {
            "content": result.content,
            "tool_calls": result.tool_calls,
            "raw": result.raw,
        }
    except AgnesAPIError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        LOGGER.exception("Chat completion failed")
        raise HTTPException(500, f"对话请求失败：{exc}")


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    """SSE streaming chat completion with optional tool calling loop."""
    if not body.messages:
        raise HTTPException(400, "消息列表不能为空")

    tools = body.tools
    tool_choice = body.tool_choice
    if body.use_tools and not tools:
        tools = _CREATIVE_TOOLS
        tool_choice = "auto"

    def event_generator():
        try:
            client = _get_client()
            gen = ChatGenerator(client)
            messages = list(body.messages)
            tool_round = 0
            max_tool_rounds = 3

            while tool_round <= max_tool_rounds:
                # ── Always use streaming, even with tools ──
                accumulated_text = ""
                accumulated_tool_calls = {}  # {index: {id, type, name, arguments}}

                stream_kwargs = {
                    "messages": messages,
                    "model": body.model,
                    "temperature": body.temperature,
                    "top_p": body.top_p,
                    "max_tokens": body.max_tokens,
                }
                if tools and tool_round < max_tool_rounds:
                    stream_kwargs["tools"] = tools
                    stream_kwargs["tool_choice"] = tool_choice

                try:
                    for chunk in gen.stream(**stream_kwargs):
                        # Stream text deltas to frontend immediately
                        if chunk.delta:
                            accumulated_text += chunk.delta
                            yield f"data: {json.dumps({'delta': chunk.delta}, ensure_ascii=False)}\n\n"

                        # Accumulate tool call deltas
                        if chunk.tool_calls_delta:
                            for tc_delta in chunk.tool_calls_delta:
                                idx = tc_delta.get("index", 0)
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = {
                                        "id": tc_delta.get("id", ""),
                                        "type": tc_delta.get("type", "function"),
                                        "function": {"name": "", "arguments": ""},
                                    }
                                existing = accumulated_tool_calls[idx]
                                if tc_delta.get("id"):
                                    existing["id"] = tc_delta["id"]
                                if tc_delta.get("type"):
                                    existing["type"] = tc_delta["type"]
                                fn_delta = tc_delta.get("function", {})
                                if fn_delta.get("name"):
                                    existing["function"]["name"] += fn_delta["name"]
                                if fn_delta.get("arguments"):
                                    existing["function"]["arguments"] += fn_delta["arguments"]
                except AgnesAPIError as exc:
                    yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
                    return

                # Check if model wants to call tools
                pending_tool_calls = list(accumulated_tool_calls.values())

                if pending_tool_calls and tool_round < max_tool_rounds:
                    # Build assistant message with tool calls
                    assistant_msg = {
                        "role": "assistant",
                        "content": accumulated_text or "",
                        "tool_calls": pending_tool_calls,
                    }
                    messages.append(assistant_msg)

                    for tc in pending_tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        tc_id = tc.get("id", "")
                        try:
                            fn_args = json.loads(fn.get("arguments", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            fn_args = {}

                        # Notify frontend: tool call starting
                        yield f"data: {json.dumps({'tool_start': {'name': fn_name, 'args': fn_args}}, ensure_ascii=False)}\n\n"

                        # Execute the tool
                        tool_result = _execute_tool_call(client, fn_name, fn_args)

                        # Notify frontend: tool call result
                        yield f"data: {json.dumps({'tool_result': {'name': fn_name, 'result': tool_result}}, ensure_ascii=False)}\n\n"

                        # Add tool result to conversation
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        })

                    tool_round += 1
                    # Loop back to let the model respond to tool results
                else:
                    # No tool calls or max rounds reached — done
                    break

            yield "data: [DONE]\n\n"

        except AgnesAPIError as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            LOGGER.exception("Chat stream failed")
            yield f"data: {json.dumps({'error': f'流式对话失败：{exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ───────── Chat Conversation Persistence ─────────

@app.post("/api/chat/save")
def save_chat_conversation(body: ChatSaveRequest):
    """Save or update a chat conversation."""
    title = body.title.strip()
    if not title:
        # Auto-generate title from first user message
        for m in body.messages:
            if m.get("role") == "user":
                title = m.get("content", "")[:60]
                break
        if not title:
            title = "新对话"
    try:
        conv_id = db.save_chat_conversation(
            conversation_id=body.conversation_id,
            title=title,
            messages=body.messages,
            model=body.model,
        )
        return {"ok": True, "conversation_id": conv_id, "title": title}
    except Exception as exc:
        LOGGER.exception("Failed to save chat conversation")
        raise HTTPException(500, f"保存对话失败：{exc}")


@app.get("/api/chat/conversations")
def list_chat_conversations():
    """List all saved chat conversations."""
    try:
        convs = db.list_chat_conversations()
        return {"conversations": convs}
    except Exception as exc:
        LOGGER.exception("Failed to list chat conversations")
        raise HTTPException(500, f"获取对话列表失败：{exc}")


@app.get("/api/chat/conversations/{conversation_id}")
def get_chat_conversation(conversation_id: int):
    """Get a specific chat conversation with full messages."""
    conv = db.get_chat_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return conv


@app.delete("/api/chat/conversations/{conversation_id}")
def delete_chat_conversation(conversation_id: int):
    """Delete a specific chat conversation."""
    db.delete_chat_conversation(conversation_id)
    return {"ok": True}


@app.delete("/api/chat/conversations")
def clear_chat_conversations():
    """Delete all chat conversations."""
    db.clear_chat_conversations()
    return {"ok": True}


# ─────────────── History ───────────────

@app.get("/api/history")
def get_history(q: str = ""):
    return {"records": db.search_history(q)}


@app.delete("/api/history/{kind}/{record_id}")
def delete_history(kind: str, record_id: int):
    db.delete_history(kind, record_id)
    return {"ok": True}


@app.delete("/api/history")
def clear_history():
    db.clear_history()
    return {"ok": True}


# ─────────────── WebSocket (Video Task Push) ───────────────

@app.websocket("/ws/video-tasks")
async def websocket_video_tasks(websocket: WebSocket):
    """WebSocket endpoint for real-time video task status updates."""
    await websocket.accept()
    async with _ws_lock:
        _ws_connections.add(websocket)
    LOGGER.info("WebSocket client connected for video tasks (total: %d)", len(_ws_connections))
    try:
        while True:
            # Keep connection alive; client can send pings or commands
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with _ws_lock:
            _ws_connections.discard(websocket)
        LOGGER.info("WebSocket client disconnected (total: %d)", len(_ws_connections))


# ─────────────── File serving ───────────────

@app.get("/api/file")
def serve_local_file(path: str):
    """Serve a local file (image or video) by absolute path."""
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(p))


@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image for image-to-video mode. Returns base64 data URI."""
    import base64, mimetypes
    content = await file.read()
    mime = file.content_type or "image/png"
    b64 = base64.b64encode(content).decode("ascii")
    return {"data_uri": f"data:{mime};base64,{b64}", "file_name": file.filename}


# ─────────────── Serve Frontend ───────────────

WEB_DIR = Path(__file__).parent / "web"

@app.get("/")
def serve_index():
    return FileResponse(str(WEB_DIR / "index.html"))

# Mount static assets
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ─────────────── Entry point ───────────────

@app.on_event("startup")
def cleanup_stuck_tasks():
    """Mark old stuck tasks (queued/in_progress) as failed on startup."""
    active_tasks = db.list_video_tasks(active_only=True)
    if not active_tasks:
        return
    now = datetime.now()
    for t in active_tasks:
        created_str = t.get("created_at", "")
        try:
            # Parse ISO timestamp or Unix timestamp
            if created_str and created_str.replace(".", "").isdigit():
                created = datetime.fromtimestamp(int(created_str))
            elif "T" in created_str:
                created = datetime.fromisoformat(created_str)
            else:
                created = now  # Can't parse → treat as recent
            age_seconds = (now - created).total_seconds()
        except (ValueError, OSError):
            age_seconds = 0

        # If task has been stuck for more than 10 minutes, mark as failed
        if age_seconds > 600:
            LOGGER.info(
                "Startup cleanup: marking stale task %s as failed (age=%ds, status=%s)",
                t.get("task_id"), age_seconds, t.get("status"),
            )
            db.update_video_task(
                task_id=t["task_id"],
                status="failed",
                error="服务重启，任务已超时自动标记为失败",
                completed_at=now.isoformat(timespec="seconds"),
            )
    LOGGER.info("Startup cleanup done. Checked %d active tasks.", len(active_tasks))


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _choose_port(default: int = 8765) -> int:
    env_port = os.environ.get("AGNESAI_PORT", "").strip()
    candidates: list[int] = []

    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            port = 0
        if 1 <= port <= 65535:
            candidates.append(port)

    candidates.extend(range(default, default + 100))

    seen: set[int] = set()
    for port in candidates:
        if port in seen:
            continue
        seen.add(port)
        if _is_port_available(port):
            return port

    raise RuntimeError(f"No available port found from {default} to {default + 99}")


def main():
    import uvicorn
    import webbrowser

    host = "127.0.0.1"
    port = _choose_port()
    url = f"http://{host}:{port}/"
    print("\n  Agnes AI Client v3.0 — Web UI")
    print(f"  {url}\n")

    if os.environ.get("AGNESAI_OPEN_BROWSER", "1").lower() not in {"0", "false", "no"}:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
