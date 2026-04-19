import logging
from functools import lru_cache

from pydantic_settings import BaseSettings
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def get_client_ip(request) -> str:
    """Extract client IP for rate limiting."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_client_ip)


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://mongo:27017"
    database_name: str = "metadata_inventory"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    request_timeout: int = 30
    max_page_source_bytes: int = 14_000_000
    user_agent: str = "Mozilla/5.0 (compatible; MetadataInventoryBot/1.0)"
    mongodb_connect_timeout: int = 30
    mongodb_connect_retries: int = 3
    rate_limit_requests_per_minute: int = 100

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def validate_settings(self) -> None:
        """Validate settings at startup. Fail fast if invalid."""
        errors = []

        if self.request_timeout < 1:
            errors.append("REQUEST_TIMEOUT must be >= 1")

        if self.max_page_source_bytes < 1:
            errors.append("MAX_PAGE_SOURCE_BYTES must be >= 1")

        if self.mongodb_connect_timeout < 1:
            errors.append("MONGODB_CONNECT_TIMEOUT must be >= 1")

        if self.mongodb_connect_retries < 0:
            errors.append("MONGODB_CONNECT_RETRIES must be >= 0")

        if not self.mongodb_url:
            errors.append("MONGODB_URL cannot be empty")

        if self.rate_limit_requests_per_minute < 1:
            errors.append("RATE_LIMIT_REQUESTS_PER_MINUTE must be >= 1")

        if errors:
            for e in errors:
                logger.error("Config validation error: %s", e)
            raise ValueError(", ".join(errors))


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings with validation."""
    settings = Settings()
    settings.validate_settings()
    return settings


settings = get_settings()
