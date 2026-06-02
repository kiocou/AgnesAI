from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.path_utils import CONFIG_DIR, ensure_directories


DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"


@dataclass
class AppConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    theme: str = "auto"
    window_width: int = 1200
    window_height: int = 800
    downloads_dir: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        ensure_directories()
        return CONFIG_DIR / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        path = cls.path()
        if not path.exists():
            config = cls()
            config.save()
            return config

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        known = {
            "api_key",
            "base_url",
            "theme",
            "window_width",
            "window_height",
            "downloads_dir",
        }
        data = {key: payload.get(key) for key in known if key in payload}
        config = cls(**data)
        config.extra = {key: value for key, value in payload.items() if key not in known}
        return config

    def save(self) -> None:
        path = self.path()
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": self.base_url or DEFAULT_BASE_URL,
            "theme": self.theme,
            "window_width": int(self.window_width),
            "window_height": int(self.window_height),
            "downloads_dir": self.downloads_dir,
        }
        payload.update(self.extra)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

