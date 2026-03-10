"""
Universal Academy Engine — Global Configuration
"""

from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # Application
    app_name: str = "Universal Academy Engine"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR}/database/uae.db"
    database_sync_url: str = f"sqlite:///{BASE_DIR}/database/uae.db"

    def model_post_init(self, __context) -> None:
        # Railway / cloud providers inject DATABASE_URL as postgresql:// or
        # postgres://, which SQLAlchemy maps to psycopg2 (sync). Normalise both
        # URLs so the correct drivers are always used.
        for sync_scheme, async_scheme in (
            ("postgres://", "postgresql+asyncpg://"),
            ("postgresql://", "postgresql+asyncpg://"),
            ("postgresql+psycopg2://", "postgresql+asyncpg://"),
        ):
            if self.database_url.startswith(sync_scheme):
                object.__setattr__(
                    self,
                    "database_url",
                    "postgresql+asyncpg://" + self.database_url[len(sync_scheme):],
                )
                break

        for sync_scheme in ("postgres://", "postgresql+asyncpg://", "postgresql://"):
            if self.database_sync_url.startswith(sync_scheme):
                object.__setattr__(
                    self,
                    "database_sync_url",
                    "postgresql+psycopg2://" + self.database_sync_url[len(sync_scheme):],
                )
                break

    # API
    api_prefix: str = "/api/v1"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Knowledge Pipeline
    default_confidence_threshold: float = 0.75
    max_claims_per_source: int = 10000
    claim_extraction_batch_size: int = 100

    # Trust Tiers
    tier1_label: str = "Primary Technical Documentation"
    tier2_label: str = "Accredited Training Sources"
    tier3_label: str = "Supplemental Sources"

    # Governance
    require_human_review_above_confidence: float = 0.95
    auto_deprecate_after_days: int = 730  # 2 years

    # v3 — Auth
    auth_enabled: bool = True
    jwt_secret: str = "change-me-in-production-minimum-32-bytes"
    jwt_algorithm: str = "HS256"
    jwt_ttl_secs: int = 3600

    # v3 — Node identity (for federation)
    node_id: str = "local-node"
    node_name: str = "Local UAE Node"
    node_url: str = "http://localhost:8000"

    # v3 — LLM
    llm_backend: str = "stub"
    llm_model_id: str = "claude-sonnet-4-6"

    # v3 — Storage
    storage_dir: str = "./storage"

    # v3 — Federation transport
    federation_replay_window_secs: int = 300
    federation_max_retries: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
