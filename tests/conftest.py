import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

import app.db.mongo as mongo_module
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def mock_db():
    """Replace the real Motor client with an in-memory mock for every test."""
    client = AsyncMongoMockClient()
    db = client["test_metadata_inventory"]

    mongo_module._client = client
    mongo_module._db = db

    await mongo_module._ensure_indexes()

    yield

    mongo_module._client = None
    mongo_module._db = None


@pytest_asyncio.fixture
async def async_client():
    """Async HTTP test client wired to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
