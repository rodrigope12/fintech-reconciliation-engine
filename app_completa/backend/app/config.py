"""
Configuration management using Pydantic Settings.
All parameters are loaded from environment variables with sensible defaults.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


import os

# Define persistent config path consistent with main_desktop.py
APP_BASE_PATH = Path(os.environ.get(
    "CONCILIACION_BASE_PATH",
    os.environ.get("APP_BASE_PATH", Path.home() / "Documents" / "conciliacion")
))
ENV_FILE_PATH = APP_BASE_PATH / ".env"

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    app_log_level: str = Field(default="INFO")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/reconciliation.db"
    )

    # Google Cloud Vision
    google_application_credentials: Optional[str] = Field(default=None)
    google_credentials_base64: Optional[str] = Field(default=None)

    # Facturama API
    facturama_api_url: str = Field(
        default="https://apisandbox.facturama.mx"
    )
    facturama_user: str = Field(default="")
    facturama_password: str = Field(default="")

    # Safe Peeling Parameters
    buffer_days: int = Field(default=5)
    hard_commit_threshold_days: int = Field(default=-2)
    uniqueness_window_days: int = Field(default=2)
    text_similarity_threshold: float = Field(default=0.7)

    # Clustering Parameters
    max_cluster_size: int = Field(default=100)
    leiden_resolution: float = Field(default=1.0)
    temporal_decay_alpha: float = Field(default=0.1)

    # Solver Parameters
    solver_timeout_seconds: int = Field(default=30)
    max_abs_delta_cents: int = Field(default=50)
    rel_delta_ratio: float = Field(default=0.001)
    fixed_gap_threshold_cents: int = Field(default=100)
    causality_buffer_days: int = Field(default=3)

    # Rescue Loop Parameters
    hard_stop_cluster_size: int = Field(default=500)
    rescue_semantic_threshold: float = Field(default=0.8)

    # NLP / Embeddings
    embedding_model: str = Field(
        default_factory=lambda: (
            str((Path(__file__).parent.parent / "data/models/paraphrase-multilingual-MiniLM-L12-v2").resolve())
            if (Path(__file__).parent.parent / "data/models/paraphrase-multilingual-MiniLM-L12-v2").exists()
            else "paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    # Storage
    upload_dir: Path = Field(default=Path("./data/uploads"))
    reports_dir: Path = Field(default=Path("./data/reports"))

    def calculate_allowed_delta(self, total_payment_cents: int) -> int:
        """
        Calculate maximum allowed error delta using hybrid formula.
        Returns: min(MAX_ABS_DELTA, amount * 0.001)
        """
        relative_limit = int(total_payment_cents * self.rel_delta_ratio)
        return min(self.max_abs_delta_cents, relative_limit)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
