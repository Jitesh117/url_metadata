import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CollectionError(Exception):
    """Raised when metadata collection fails for any reason."""


async def collect_metadata(url: str) -> dict[str, Any]:
    """Fetch *url* and return headers, cookies, and page_source."""
    logger.info("Collecting metadata for %s", url)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.request_timeout,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            async with client.stream("GET", url) as response:
                headers = dict(response.headers)
                cookies = dict(response.cookies)
                chunks: list[bytes] = []
                body_size = 0

                async for chunk in response.aiter_bytes():
                    body_size += len(chunk)
                    if body_size > settings.max_page_source_bytes:
                        msg = (
                            f"Response body too large ({body_size} bytes). "
                            "Maximum allowed is "
                            f"{settings.max_page_source_bytes} bytes."
                        )
                        logger.warning(msg)
                        raise CollectionError(msg)
                    chunks.append(chunk)

                content = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                try:
                    page_source = content.decode(encoding, errors="replace")
                except LookupError:
                    page_source = content.decode("utf-8", errors="replace")

        logger.info(
            "Collected metadata for %s (status=%s, body_len=%d)",
            url,
            response.status_code,
            len(page_source),
        )
        return {"headers": headers, "cookies": cookies, "page_source": page_source}

    except CollectionError:
        raise

    except httpx.TimeoutException as exc:
        msg = f"Request timed out after {settings.request_timeout}s: {exc}"
        logger.warning(msg)
        raise CollectionError(msg) from exc

    except httpx.RequestError as exc:
        msg = f"Network error while fetching {url}: {exc}"
        logger.warning(msg)
        raise CollectionError(msg) from exc

    except Exception as exc:
        msg = f"Unexpected error while collecting {url}: {exc}"
        logger.exception(msg)
        raise CollectionError(msg) from exc
