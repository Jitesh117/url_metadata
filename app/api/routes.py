import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from app.db.mongo import (
    find_metadata_by_url,
    mark_completed,
    mark_pending_if_absent,
)
from app.models.schemas import (
    AcknowledgementResponse,
    CollectionStatus,
    MetadataRequest,
    MetadataResponse,
)
from app.services.collector import CollectionError, collect_metadata
from app.worker.tasks import collect_and_store
from app.config import get_settings, limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metadata", tags=["metadata"])


def get_rate_limit() -> str:
    """Get rate limit from config."""
    settings = get_settings()
    return f"{settings.rate_limit_requests_per_minute}/minute"


def _doc_to_response(doc: dict) -> MetadataResponse:
    """Convert a raw MongoDB document into a MetadataResponse."""
    return MetadataResponse(
        id=str(doc.get("_id")),
        url=doc["url"],
        status=doc["status"],
        headers=doc.get("headers"),
        cookies=doc.get("cookies"),
        page_source=doc.get("page_source"),
        error=doc.get("error"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MetadataResponse,
    summary="Collect and store metadata for a URL",
    responses={
        409: {"description": "Collection already in progress"},
        422: {"description": "Invalid URL"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Metadata collection failed"},
        503: {"description": "Database not ready"},
        500: {"description": "Collection or database error"},
    },
)
@limiter.limit(get_rate_limit())
async def create_metadata(request: Request, body: MetadataRequest) -> MetadataResponse:
    """Synchronously fetch headers, cookies, and page source for *url*."""
    url = str(body.url)

    try:
        existing = await find_metadata_by_url(url)
        if existing:
            existing_status = existing["status"]

            if existing_status == CollectionStatus.PENDING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Collection already in progress for this URL",
                )
    except RuntimeError as exc:
        logger.warning("Database unavailable while reading %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready",
        ) from exc

    try:
        data = await collect_metadata(url)
    except CollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to collect metadata: {exc}",
        ) from exc

    try:
        await mark_completed(
            url,
            headers=data["headers"],
            cookies=data["cookies"],
            page_source=data["page_source"],
        )
    except RuntimeError as exc:
        logger.warning("Database unavailable while writing %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready",
        ) from exc
    except Exception as exc:
        logger.exception("Database write failed for %s", url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {exc}",
        ) from exc

    try:
        doc = await find_metadata_by_url(url)
    except RuntimeError as exc:
        logger.warning("Database unavailable while reading %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready",
        ) from exc
    return _doc_to_response(doc)


@router.get(
    "",
    summary="Retrieve metadata for a URL",
    responses={
        200: {"description": "Metadata found and returned"},
        202: {"description": "URL not in inventory or pending"},
        422: {"description": "Invalid URL"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "Database not ready"},
    },
)
@limiter.limit(get_rate_limit())
async def get_metadata(
    request: Request,
    url: Annotated[
        HttpUrl, Query(description="The URL whose metadata should be retrieved")
    ],
):
    """Return stored metadata for *url*."""
    normalized_url = str(url)

    try:
        doc = await find_metadata_by_url(normalized_url)
    except RuntimeError as exc:
        logger.warning(
            "Database unavailable while reading %s: %s", normalized_url, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready",
        ) from exc

    if doc is not None:
        record_status = doc["status"]

        if record_status == CollectionStatus.COMPLETED:
            return _doc_to_response(doc)

        if record_status == CollectionStatus.PENDING:
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=AcknowledgementResponse(
                    message="Collection in progress. Please retry your request shortly.",
                    url=normalized_url,
                    status=CollectionStatus.PENDING,
                ).model_dump(),
            )

        if record_status == CollectionStatus.FAILED:
            return _doc_to_response(doc)

    try:
        inserted = await mark_pending_if_absent(normalized_url)
    except RuntimeError as exc:
        logger.warning(
            "Database unavailable while writing %s: %s", normalized_url, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready",
        ) from exc

    if inserted:
        asyncio.create_task(collect_and_store(normalized_url))
        message = (
            "URL not found in inventory. "
            "Metadata collection has been scheduled; "
            "please retry your request shortly."
        )
    else:
        # Another request inserted this URL concurrently.
        try:
            latest_doc = await find_metadata_by_url(normalized_url)
        except RuntimeError as exc:
            logger.warning(
                "Database unavailable while reading %s: %s", normalized_url, exc
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not ready",
            ) from exc
        if latest_doc is not None and latest_doc["status"] == CollectionStatus.COMPLETED:
            return _doc_to_response(latest_doc)
        if latest_doc is not None and latest_doc["status"] == CollectionStatus.FAILED:
            return _doc_to_response(latest_doc)
        message = "Collection in progress. Please retry your request shortly."

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=AcknowledgementResponse(
            message=message,
            url=normalized_url,
            status=CollectionStatus.PENDING,
        ).model_dump(),
    )
