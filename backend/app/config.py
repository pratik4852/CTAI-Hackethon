"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    app_name: str = "MEPIQ"
    version: str = "1.0.0"

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MEPIQ_DATA_DIR", "./data")).resolve())
    max_upload_mb: int = field(default_factory=lambda: _int("MEPIQ_MAX_UPLOAD_MB", 200))
    max_sheets: int = field(default_factory=lambda: _int("MEPIQ_MAX_SHEETS", 40))
    workers: int = field(default_factory=lambda: _int("MEPIQ_WORKERS", 2))
    render_dpi: int = field(default_factory=lambda: _int("MEPIQ_RENDER_DPI", 150))

    cors_origins: str = field(default_factory=lambda: os.getenv("MEPIQ_CORS_ORIGINS", "*"))

    # --- Copilot -----------------------------------------------------------
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip())
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "").strip())
    copilot_max_tool_calls: int = field(default_factory=lambda: _int("MEPIQ_COPILOT_MAX_TOOL_CALLS", 6))

    # --- Frontend bundle served by the API (single-container mode) ---------
    static_dir: str = field(default_factory=lambda: os.getenv("MEPIQ_STATIC_DIR", "").strip())

    @property
    def uploads(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results(self) -> Path:
        return self.data_dir / "results"

    @property
    def library_path(self) -> Path:
        return self.data_dir / "library" / "symbol_library.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mepiq.db"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.uploads, self.results, self.library_path.parent):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
