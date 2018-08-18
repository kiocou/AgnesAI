from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    """Config file lives next to exe when frozen, otherwise in project config/."""
    if getattr(sys, "frozen", False):
        return app_root() / "config.json"
    return CONFIG_DIR / "config.json"


ROOT_DIR = app_root()
CONFIG_DIR = ROOT_DIR / "config"
DATABASE_DIR = ROOT_DIR / "database"
LOGS_DIR = ROOT_DIR / "logs"
ASSETS_DIR = ROOT_DIR / "assets"
HISTORY_DIR = ROOT_DIR / "history"
IMAGE_HISTORY_DIR = HISTORY_DIR / "images"
VIDEO_HISTORY_DIR = HISTORY_DIR / "videos"
DOWNLOADS_DIR = ROOT_DIR / "downloads"


def ensure_directories() -> None:
    for directory in (
        CONFIG_DIR,
        DATABASE_DIR,
        LOGS_DIR,
        ASSETS_DIR,
        HISTORY_DIR,
        IMAGE_HISTORY_DIR,
        VIDEO_HISTORY_DIR,
        DOWNLOADS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def safe_filename(value: str, fallback: str = "file") -> str:
    invalid = '<>:"/\\|?*\0'
    cleaned = "".join("_" if ch in invalid else ch for ch in value).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned[:180] or fallback
