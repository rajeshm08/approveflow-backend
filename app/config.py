import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL") or "sqlite:///./approveflow.db"
    secret_key: str = os.getenv("SECRET_KEY", "development-only-change-me")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    frontend_url: str = os.getenv("FRONTEND_URL", "https://approveflow-ai.vercel.app")
    demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes"}
    upload_directory: Path = Path(
        os.getenv("UPLOAD_DIRECTORY", str(Path(__file__).resolve().parents[1] / "private_uploads"))
    ).resolve()

    @property
    def cors_origins(self) -> list[str]:
        configured = os.getenv("CORS_ORIGINS", "http://localhost:5173")
        origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
        if self.frontend_url and self.frontend_url not in origins:
            origins.append(self.frontend_url)
        return origins


settings = Settings()
