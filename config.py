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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
