import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


DEFAULT_SECRET_KEY = "development-only-change-me"


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Settings:
    configured_database_url = os.getenv("DATABASE_URL")
    database_url: str = (
        normalize_database_url(configured_database_url.strip())
        if configured_database_url and configured_database_url.strip()
        else "sqlite:///./approveflow.db"
    )
    secret_key: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes"}
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes"}
    document_expiry_alert_offsets_days: tuple[int, ...] = tuple(
        int(offset.strip())
        for offset in os.getenv("DOCUMENT_EXPIRY_ALERT_OFFSETS_DAYS", "30,15,7").split(",")
        if offset.strip()
    )
    document_expiry_escalation_grace_days: int = int(
        os.getenv("DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS", "3")
    )
    upload_directory: Path = Path(
        os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "private_uploads"))
    ).resolve()

    @property
    def cors_origins(self) -> list[str]:
        configured = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    def validate_runtime_settings(self) -> None:
        production_mode = (
            os.getenv("RENDER", "").lower() == "true"
            or os.getenv("ENVIRONMENT", "").lower() == "production"
        )
        if production_mode and self.secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError("SECRET_KEY must be set to a secure value in production.")


settings = Settings()
