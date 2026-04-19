import logging
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.routes import router
from app.config import get_settings, limiter
from app.db.mongo import close_db, connect_db, get_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def wait_for_mongo(max_retries: int = 3, delay: float = 5.0) -> bool:
    """Wait for MongoDB to be ready with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            await connect_db()
            return True
        except Exception as exc:
            wait_time = delay * (2**attempt)
            logger.warning(
                "MongoDB connection attempt %d/%d failed: %s. Retrying in %.1fs...",
                attempt + 1,
                max_retries,
                exc,
                wait_time,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)

    logger.error("Failed to connect to MongoDB after %d attempts", max_retries)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application-level resources across the process lifetime."""
    settings = get_settings()
    logger.info("Starting up – validating configuration...")
    settings.validate_settings()

    logger.info(
        "Starting up – connecting to MongoDB (retries=%d)...",
        settings.mongodb_connect_retries,
    )

    connected = await wait_for_mongo(
        max_retries=settings.mongodb_connect_retries,
        delay=float(settings.mongodb_connect_timeout),
    )

    if not connected:
        logger.error("Failed to connect to MongoDB on startup")
        raise RuntimeError("Unable to connect to MongoDB during startup")

    yield

    logger.info("Shutting down – closing MongoDB connection…")
    await close_db()


app = FastAPI(
    title="HTTP Metadata Inventory",
    description=(
        "Collects and stores HTTP response headers, cookies, "
        "and page source for arbitrary URLs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    # allows all currently, since we are in dev right now and there's no frontend to serve this to, only the swagger UI
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/health", tags=["health"], summary="Service health check")
async def health_check() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"], summary="Readiness check")
async def readiness_check() -> dict:
    """Readiness probe that checks database connectivity."""
    try:
        await get_client().admin.command("ping")
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database not ready")
    return {"status": "ready"}
