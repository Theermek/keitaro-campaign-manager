from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base URL already includes /admin_api/v1
    keitaro_api_url: str
    keitaro_api_key: SecretStr
    keitaro_timeout: float = 15.0

    # Only campaigns with this prefix may be created or changed
    campaign_prefix: str

    # Reference objects for new campaigns, by name; IDs are resolved via the API
    keitaro_domain: str
    keitaro_group: str
    keitaro_source: str

    database_url: str = "sqlite:///./app.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
