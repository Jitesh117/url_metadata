from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, HttpUrl, TypeAdapter, field_validator

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class CollectionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class MetadataRequest(BaseModel):
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def url_must_have_scheme(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https scheme")
        return v


def normalize_url(url: Union[str, HttpUrl]) -> str:
    """Return a canonical URL representation used for DB keys."""
    return str(_HTTP_URL_ADAPTER.validate_python(str(url)))


class MetadataResponse(BaseModel):
    id: str
    url: str
    status: CollectionStatus
    headers: Optional[Dict[str, Any]] = None
    cookies: Optional[Dict[str, Any]] = None
    page_source: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcknowledgementResponse(BaseModel):
    message: str
    url: str
    status: CollectionStatus = CollectionStatus.PENDING
