from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    storage_backend: str = "local"
    app_secret_key: str = "local-development-only-change-me"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_bucket: str = "speaker-audio"
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    config: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.getenv("PROJECT_ROOT", PROJECT_ROOT)).resolve()
        with (root / "config.yaml").open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}
        origins = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if item.strip()]
        return cls(
            project_root=root,
            storage_backend=os.getenv("STORAGE_BACKEND", "local").lower(),
            app_secret_key=os.getenv("APP_SECRET_KEY", "local-development-only-change-me"),
            supabase_url=os.getenv("SUPABASE_URL", ""),
            supabase_service_role_key=os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")),
            supabase_bucket=os.getenv("SUPABASE_AUDIO_BUCKET", "speaker-audio"),
            allowed_origins=origins,
            config=config,
        )

    @property
    def languages(self): return tuple(self.config.get("languages", {}).keys()) or ("english", "hindi", "telugu", "khasi")

    @property
    def sessions_per_language(self): return int(self.config["recording"].get("sessions_per_language", 2))

    @property
    def utterances_per_session(self): return int(self.config["recording"].get("read_utterances_per_session", 10))

    @property
    def max_utterance_duration_seconds(self): return float(self.config["recording"].get("max_utterance_duration_seconds", 30))

    def path(self, config_key: str) -> Path:
        return self.project_root / self.config["paths"][config_key]

    def validate(self):
        if self.storage_backend not in ("local", "supabase"):
            raise ValueError("STORAGE_BACKEND must be local or supabase.")
        if self.storage_backend == "supabase" and not (self.supabase_url and self.supabase_service_role_key):
            raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for Supabase mode.")
        if self.storage_backend == "supabase" and len(self.app_secret_key) < 32:
            raise ValueError("Set APP_SECRET_KEY to a random value of at least 32 characters in Supabase mode.")
        if self.sessions_per_language != 2 or self.utterances_per_session != 10:
            raise ValueError("This collection app is configured for exactly 2 sessions with 10 utterances each.")
