"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Security-hardened settings container."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    openai_api_key: str
    rate_limit_per_min: int = 10


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings, raising if required keys are missing."""
    return Settings()


settings = get_settings()
