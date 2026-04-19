import pytest

from app.db.mongo import (
    find_metadata_by_url,
    mark_completed,
    mark_failed,
    mark_pending,
    mark_pending_if_absent,
)
from app.models.schemas import CollectionStatus

SAMPLE_URL = "https://example.com"


@pytest.mark.asyncio
async def test_mark_pending_creates_record():
    await mark_pending(SAMPLE_URL)
    doc = await find_metadata_by_url(SAMPLE_URL)

    assert doc is not None
    assert doc["url"].rstrip("/") == SAMPLE_URL.rstrip("/")
    assert doc["status"] == CollectionStatus.PENDING
    assert "created_at" in doc
    assert "updated_at" in doc


@pytest.mark.asyncio
async def test_mark_completed_stores_data():
    headers = {"content-type": "text/html"}
    cookies = {"session": "xyz"}
    page_source = "<html>Hello</html>"

    await mark_completed(
        SAMPLE_URL, headers=headers, cookies=cookies, page_source=page_source
    )
    doc = await find_metadata_by_url(SAMPLE_URL)

    assert doc["status"] == CollectionStatus.COMPLETED
    assert doc["headers"] == headers
    assert doc["cookies"] == cookies
    assert doc["page_source"] == page_source
    assert doc["error"] is None


@pytest.mark.asyncio
async def test_mark_failed_stores_error():
    error_msg = "Connection refused"
    await mark_failed(SAMPLE_URL, error_msg)
    doc = await find_metadata_by_url(SAMPLE_URL)

    assert doc["status"] == CollectionStatus.FAILED
    assert doc["error"] == error_msg


@pytest.mark.asyncio
async def test_upsert_preserves_created_at():
    """created_at must not change across multiple upserts."""
    await mark_pending(SAMPLE_URL)
    doc_before = await find_metadata_by_url(SAMPLE_URL)

    await mark_completed(SAMPLE_URL, headers={}, cookies={}, page_source="")
    doc_after = await find_metadata_by_url(SAMPLE_URL)

    assert doc_before["created_at"] == doc_after["created_at"]
    assert doc_after["updated_at"] >= doc_before["updated_at"]


@pytest.mark.asyncio
async def test_find_metadata_returns_none_for_unknown_url():
    result = await find_metadata_by_url("https://not-in-db.example.com")
    assert result is None


@pytest.mark.asyncio
async def test_mark_pending_if_absent_is_atomic():
    first_insert = await mark_pending_if_absent(SAMPLE_URL)
    second_insert = await mark_pending_if_absent(SAMPLE_URL)

    assert first_insert is True
    assert second_insert is False
