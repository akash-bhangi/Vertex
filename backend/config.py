import os
from typing import List, Optional
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    # Required
    FIRMS_MAP_KEY: str
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: Optional[str] = None
    GEMINI_API_KEY: str

    # Optional
    EARTHDATA_USER: Optional[str] = None
    EARTHDATA_PASS: Optional[str] = None
    CDSE_CLIENT_ID: Optional[str] = None
    CDSE_CLIENT_SECRET: Optional[str] = None

    # App Config
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "*"
    BACKEND_PORT: int = 8000
    AI_CLASSIFICATION_LIMIT: int = 50
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Admin Seeding
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "admin123"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS as comma-separated string into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = {
        "env_file": (str(BASE_DIR / ".env"), str(BASE_DIR.parent / ".env")),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

settings = Settings()
