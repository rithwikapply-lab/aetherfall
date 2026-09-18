from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Aetherfall"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database & Cache (Defaults to local zero-dependency SQLite)
    DATABASE_URL: str = "sqlite+aiosqlite:///./aetherfall.db"
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    # LLM Provider (Optional - mock/local fallback enabled when empty)
    ANTHROPIC_API_KEY: Optional[str] = None
    LLM_MODEL: str = "claude-sonnet-4-5"

    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
