import asyncio
import logging

from app.db.mongo import mark_completed, mark_failed
from app.services.collector import CollectionError, collect_metadata

logger = logging.getLogger(__name__)


async def _safe_mark_failed(url: str, error: str) -> None:
    """Best-effort failed-state update that never raises."""
    try:
        await mark_failed(url, error)
    except Exception:
        logger.exception("Failed to persist failed status for %s", url)


async def collect_and_store(url: str) -> None:
    """Fetch metadata for *url* and persist the result."""
    logger.info("Background collection started for %s", url)
    try:
        data = await collect_metadata(url)
        await mark_completed(
            url,
            headers=data["headers"],
            cookies=data["cookies"],
            page_source=data["page_source"],
        )
        logger.info("Background collection completed for %s", url)

    except CollectionError as exc:
        logger.warning("Background collection failed for %s: %s", url, exc)
        await _safe_mark_failed(url, str(exc))

    except asyncio.CancelledError:
        logger.warning("Background collection cancelled for %s", url)
        await _safe_mark_failed(url, "Collection cancelled (application shutdown)")
        raise

    except Exception as exc:
        logger.exception("Unexpected error in background collection for %s", url)
        await _safe_mark_failed(url, f"Unexpected error: {exc}")
