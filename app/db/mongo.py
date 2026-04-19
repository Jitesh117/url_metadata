import logging
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings
from app.models.schemas import CollectionStatus, normalize_url

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("Database client has not been initialised.")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database has not been initialised.")
    return _db


async def connect_db(mongodb_url: Optional[str] = None) -> None:
    """Create the Motor client and ensure indexes exist."""
    global _client, _db

    url = mongodb_url or settings.mongodb_url
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5_000)
    db = client[settings.database_name]

    try:
        await db.command("ping")
        await _ensure_indexes(db)
    except Exception:
        client.close()
        raise

    _client = client
    _db = db
    logger.info("Connected to MongoDB at %s (db: %s)", url, settings.database_name)


async def close_db() -> None:
    """Close the Motor client gracefully."""
    global _client, _db

    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed.")


async def _ensure_indexes(db: Optional[AsyncIOMotorDatabase] = None) -> None:
    """Create indexes on the metadata collection if they do not exist."""
    database = db if db is not None else get_db()
    collection = database["metadata"]
    await collection.create_index("url", unique=True)
    await collection.create_index("created_at")
    logger.debug("MongoDB indexes ensured.")


def get_metadata_collection():
    """Return the *metadata* collection from the active database."""
    return get_db()["metadata"]


async def find_metadata_by_url(url: str) -> Optional[dict]:
    """Return the stored metadata document for *url*, or None."""
    collection = get_metadata_collection()
    canonical_url = normalize_url(url)
    return await collection.find_one({"url": canonical_url})


async def upsert_metadata(url: str, data: dict[str, Any]) -> None:
    """Insert or update a metadata document identified by *url*."""
    collection = get_metadata_collection()
    now = datetime.now(timezone.utc)
    canonical_url = normalize_url(url)
    payload = {k: v for k, v in data.items() if k != "url"}

    await collection.update_one(
        {"url": canonical_url},
        {
            "$set": {**payload, "updated_at": now},
            "$setOnInsert": {"created_at": now, "url": canonical_url},
        },
        upsert=True,
    )


async def mark_pending(url: str) -> None:
    """Insert a *pending* placeholder document for *url* (idempotent)."""
    await upsert_metadata(url, {"status": CollectionStatus.PENDING})


async def mark_pending_if_absent(url: str) -> bool:
    """
    Insert a pending placeholder only if the URL does not exist yet.

    Returns True when a new document is inserted, False when it already exists.
    """
    collection = get_metadata_collection()
    now = datetime.now(timezone.utc)
    canonical_url = normalize_url(url)

    result = await collection.update_one(
        {"url": canonical_url},
        {
            "$setOnInsert": {
                "url": canonical_url,
                "status": CollectionStatus.PENDING,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return result.upserted_id is not None


async def mark_completed(
    url: str,
    headers: dict[str, Any],
    cookies: dict[str, Any],
    page_source: str,
) -> None:
    """Persist successfully collected data for *url*."""
    await upsert_metadata(
        url,
        {
            "status": CollectionStatus.COMPLETED,
            "headers": headers,
            "cookies": cookies,
            "page_source": page_source,
            "error": None,
        },
    )


async def mark_failed(url: str, error: str) -> None:
    """Record a failed collection attempt for *url*."""
    await upsert_metadata(
        url,
        {
            "status": CollectionStatus.FAILED,
            "error": error,
        },
    )
