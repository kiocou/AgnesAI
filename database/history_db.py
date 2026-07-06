from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.path_utils import DATABASE_DIR, ensure_directories


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class HistoryDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        ensure_directories()
        self.path = Path(path) if path else DATABASE_DIR / "history.db"
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS image_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    negative_prompt TEXT DEFAULT '',
                    model TEXT NOT NULL,
                    size TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    seed TEXT DEFAULT '',
                    result_urls TEXT NOT NULL,
                    local_paths TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS video_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    video_id TEXT DEFAULT '',
                    prompt TEXT NOT NULL,
                    negative_prompt TEXT DEFAULT '',
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    fps INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER DEFAULT 0,
                    result_url TEXT DEFAULT '',
                    local_path TEXT DEFAULT '',
                    source_image_path TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT DEFAULT '',
                    error TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    progress INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    save_path TEXT NOT NULL,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT '',
                    messages TEXT NOT NULL DEFAULT '[]',
                    model TEXT NOT NULL DEFAULT 'agnes-2.0-flash',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "video_history", "source_image_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "video_history", "video_id", "TEXT DEFAULT ''")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _decode_json_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value]
        if not isinstance(value, str) or not value.strip():
            return []
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",")]
        if isinstance(decoded, list):
            return [str(item) if item is not None else "" for item in decoded]
        return []

    @staticmethod
    def _sort_timestamp(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            timestamp = float(text)
            if timestamp > 9_999_999_999:
                timestamp /= 1000
            return timestamp
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def insert_image_history(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        model: str,
        size: str,
        count: int,
        seed: str,
        result_urls: list[str],
        local_paths: list[str],
    ) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO image_history
                (prompt, negative_prompt, model, size, count, seed, result_urls, local_paths, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt,
                    negative_prompt,
                    model,
                    size,
                    count,
                    seed,
                    json.dumps(result_urls, ensure_ascii=False),
                    json.dumps(local_paths, ensure_ascii=False),
                    now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def insert_video_task(
        self,
        *,
        task_id: str,
        video_id: str = "",
        prompt: str,
        negative_prompt: str,
        model: str,
        mode: str,
        resolution: str,
        duration_seconds: int,
        fps: int,
        status: str,
        progress: int,
        created_at: str = "",
        source_image_path: str = "",
    ) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO video_history
                (task_id, video_id, prompt, negative_prompt, model, mode, resolution, duration_seconds, fps,
                 status, progress, result_url, local_path, source_image_path, created_at, completed_at, error)
                VALUES (?, COALESCE(NULLIF(?, ''), (SELECT video_id FROM video_history WHERE task_id=?), ''),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT result_url FROM video_history WHERE task_id=?), ''),
                        COALESCE((SELECT local_path FROM video_history WHERE task_id=?), ''),
                        ?, COALESCE(NULLIF(?, ''), ?), '', '')
                """,
                (
                    task_id,
                    video_id,
                    task_id,
                    prompt,
                    negative_prompt,
                    model,
                    mode,
                    resolution,
                    duration_seconds,
                    fps,
                    status,
                    progress,
                    task_id,
                    task_id,
                    source_image_path,
                    created_at,
                    now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def update_video_task(
        self,
        *,
        task_id: str,
        status: str,
        progress: int = 0,
        result_url: str = "",
        completed_at: str = "",
        error: str = "",
        local_path: str = "",
        video_id: str = "",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE video_history
                SET status = ?,
                    progress = ?,
                    video_id = COALESCE(NULLIF(?, ''), video_id),
                    result_url = COALESCE(NULLIF(?, ''), result_url),
                    completed_at = COALESCE(NULLIF(?, ''), completed_at),
                    error = COALESCE(NULLIF(?, ''), error),
                    local_path = COALESCE(NULLIF(?, ''), local_path)
                WHERE task_id = ?
                """,
                (status, progress, video_id, result_url, completed_at, error, local_path, task_id),
            )

    def search_history(self, keyword: str = "") -> list[dict[str, Any]]:
        keyword = f"%{keyword.strip()}%"
        rows: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            image_rows = conn.execute(
                """
                SELECT id, 'image' AS kind, created_at, model, prompt, negative_prompt,
                       size AS meta, result_urls AS result_url, local_paths AS local_path, '' AS status,
                       size, count, seed, '' AS task_id, '' AS video_id, '' AS mode, '' AS resolution,
                       0 AS duration_seconds, 0 AS fps
                FROM image_history
                WHERE prompt LIKE ? OR model LIKE ?
                ORDER BY created_at DESC
                """,
                (keyword, keyword),
            ).fetchall()
            video_rows = conn.execute(
                """
                SELECT id, 'video' AS kind, created_at, model, prompt, negative_prompt,
                       resolution || ' / ' || duration_seconds || 's' AS meta,
                       result_url, local_path, status,
                       '' AS size, 0 AS count, '' AS seed, task_id, video_id, mode, resolution,
                       source_image_path,
                       duration_seconds, fps
                FROM video_history
                WHERE prompt LIKE ? OR model LIKE ? OR task_id LIKE ?
                ORDER BY created_at DESC
                """,
                (keyword, keyword, keyword),
            ).fetchall()

        for row in image_rows + video_rows:
            item = dict(row)
            if item["kind"] == "image":
                result_urls = self._decode_json_list(item["result_url"])
                local_paths = self._decode_json_list(item["local_path"])
                image_count = max(len(result_urls), len(local_paths), int(item.get("count") or 0))
                images: list[dict[str, str]] = []
                for index in range(image_count):
                    url = result_urls[index] if index < len(result_urls) else ""
                    local_path = local_paths[index] if index < len(local_paths) else ""
                    if url or local_path:
                        images.append({"url": url, "local_path": local_path})
                item["result_urls"] = result_urls
                item["local_paths"] = local_paths
                item["images"] = images
                item["result_url"] = ", ".join(url for url in result_urls if url)
                item["local_path"] = ", ".join(path for path in local_paths if path)
            rows.append(item)
        rows.sort(
            key=lambda value: (
                self._sort_timestamp(value.get("created_at")),
                int(value.get("id") or 0),
            ),
            reverse=True,
        )
        return rows

    def delete_history(self, kind: str, record_id: int) -> None:
        table = "image_history" if kind == "image" else "video_history"
        with self._lock, self._connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))

    def clear_history(self, kind: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            if kind == "image":
                conn.execute("DELETE FROM image_history")
            elif kind == "video":
                conn.execute("DELETE FROM video_history")
            else:
                conn.execute("DELETE FROM image_history")
                conn.execute("DELETE FROM video_history")

    def list_video_tasks(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if active_only:
                rows = conn.execute(
                    """
                    SELECT * FROM video_history
                    WHERE status IN (
                        'queued', 'pending', 'submitted', 'starting', 'started', 'waiting', 'inference',
                        'in_progress', 'processing', 'running', 'generating', 'rendering'
                    )
                    ORDER BY id DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM video_history ORDER BY id DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def add_download(
        self,
        *,
        file_name: str,
        file_type: str,
        save_path: str,
        url: str,
        status: str = "queued",
    ) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO downloads
                (file_name, file_type, size, progress, status, save_path, url, created_at, updated_at)
                VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?)
                """,
                (file_name, file_type, status, save_path, url, now_iso(), now_iso()),
            )
            return int(cursor.lastrowid)

    def update_download(
        self,
        download_id: int,
        *,
        size: int | None = None,
        progress: int | None = None,
        status: str | None = None,
        save_path: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            current = conn.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
            if not current:
                return
            conn.execute(
                """
                UPDATE downloads
                SET size = ?, progress = ?, status = ?, save_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    current["size"] if size is None else size,
                    current["progress"] if progress is None else progress,
                    current["status"] if status is None else status,
                    current["save_path"] if save_path is None else save_path,
                    now_iso(),
                    download_id,
                ),
            )

    def delete_download(self, download_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))

    def list_downloads(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM downloads ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    # ───────── Chat Conversations ─────────

    def save_chat_conversation(
        self,
        *,
        conversation_id: int | None = None,
        title: str,
        messages: list[dict[str, Any]],
        model: str = "agnes-2.0-flash",
    ) -> int:
        """Insert or update a chat conversation. Returns the conversation id."""
        ts = now_iso()
        with self._lock, self._connect() as conn:
            if conversation_id:
                conn.execute(
                    """
                    UPDATE chat_conversations
                    SET title = ?, messages = ?, model = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (title, json.dumps(messages, ensure_ascii=False), model, ts, conversation_id),
                )
                return conversation_id
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO chat_conversations
                    (title, messages, model, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (title, json.dumps(messages, ensure_ascii=False), model, ts, ts),
                )
                return int(cursor.lastrowid)

    def list_chat_conversations(self) -> list[dict[str, Any]]:
        """Return all chat conversations (id, title, model, created_at, updated_at, message_count)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, model, created_at, updated_at,
                       json_array_length(messages) AS message_count
                FROM chat_conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_chat_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        """Return a single chat conversation with full messages."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["messages"] = json.loads(item.get("messages", "[]"))
        return item

    def delete_chat_conversation(self, conversation_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_conversations WHERE id = ?", (conversation_id,))

    def clear_chat_conversations(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_conversations")
