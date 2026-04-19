import pytest
from pytest_mock import MockerFixture

from app.db.mongo import mark_completed, mark_pending, mark_failed
from app.models.schemas import CollectionStatus
from app.services.collector import CollectionError

SAMPLE_URL = "https://example.com"
SAMPLE_DATA = {
    "headers": {"content-type": "text/html"},
    "cookies": {"session": "abc"},
    "page_source": "<html>Hello</html>",
}


@pytest.mark.asyncio
async def test_post_metadata_success(async_client, mocker: MockerFixture):
    """POST returns 201 with a completed metadata record."""
    mocker.patch(
        "app.api.routes.collect_metadata",
        return_value=SAMPLE_DATA,
    )

    response = await async_client.post("/metadata", json={"url": SAMPLE_URL})

    assert response.status_code == 201
    body = response.json()
    assert body["url"].rstrip("/") == SAMPLE_URL.rstrip("/")
    assert body["status"] == "completed"
    assert body["headers"] == SAMPLE_DATA["headers"]
    assert body["cookies"] == SAMPLE_DATA["cookies"]
    assert body["page_source"] == SAMPLE_DATA["page_source"]
    assert body["error"] is None


@pytest.mark.asyncio
async def test_post_metadata_invalid_url(async_client):
    """POST with a non-URL string returns 422."""
    response = await async_client.post("/metadata", json={"url": "not-a-url"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_metadata_collection_error(async_client, mocker: MockerFixture):
    """POST returns 502 when the collector fails."""
    mocker.patch(
        "app.api.routes.collect_metadata",
        side_effect=CollectionError("timeout"),
    )

    response = await async_client.post("/metadata", json={"url": SAMPLE_URL})
    assert response.status_code == 502
    assert "timeout" in response.json()["detail"]


@pytest.mark.asyncio
async def test_post_metadata_existing_completed_recollects(
    async_client, mocker: MockerFixture
):
    """POST on existing completed URL re-fetches and overwrites."""
    await mark_completed(
        SAMPLE_URL,
        headers={"existing": "header"},
        cookies={},
        page_source="existing content",
    )

    new_data = {
        "headers": {"new": "header"},
        "cookies": {"k": "v"},
        "page_source": "new content",
    }
    mock_collect = mocker.patch("app.api.routes.collect_metadata", return_value=new_data)

    response = await async_client.post("/metadata", json={"url": SAMPLE_URL})

    assert response.status_code == 201
    assert response.json()["page_source"] == "new content"
    mock_collect.assert_called_once()


@pytest.mark.asyncio
async def test_post_existing_pending_returns_409(async_client, mocker: MockerFixture):
    """POST on pending URL attempts to return 409 Conflict."""
    mocker.patch(
        "app.api.routes.find_metadata_by_url",
        return_value={
            "_id": "test123",
            "url": SAMPLE_URL,
            "status": CollectionStatus.PENDING,
        },
    )

    response = await async_client.post("/metadata", json={"url": SAMPLE_URL})

    assert response.status_code == 409
    assert "in progress" in response.json()["detail"]


@pytest.mark.asyncio
async def test_post_metadata_overwrites_failed(async_client, mocker: MockerFixture):
    """POST on failed URL re-fetches and overwrites."""
    await mark_failed(SAMPLE_URL, "Previous error")

    new_data = {
        "headers": {"new": "header"},
        "cookies": {"k": "v"},
        "page_source": "new content",
    }
    mocker.patch("app.api.routes.collect_metadata", return_value=new_data)

    response = await async_client.post("/metadata", json={"url": SAMPLE_URL})

    assert response.status_code == 201
    assert response.json()["page_source"] == "new content"


@pytest.mark.asyncio
async def test_get_metadata_completed(async_client):
    """GET returns 200 with full data when completed record exists."""
    await mark_completed(
        SAMPLE_URL,
        headers=SAMPLE_DATA["headers"],
        cookies=SAMPLE_DATA["cookies"],
        page_source=SAMPLE_DATA["page_source"],
    )

    response = await async_client.get("/metadata", params={"url": SAMPLE_URL})

    assert response.status_code == 200
    body = response.json()
    assert body["url"].rstrip("/") == SAMPLE_URL.rstrip("/")
    assert body["status"] == "completed"
    assert body["headers"] == SAMPLE_DATA["headers"]


@pytest.mark.asyncio
async def test_get_metadata_normalizes_url(async_client, mocker: MockerFixture):
    """POST and GET should treat equivalent URL forms as the same record."""
    mocker.patch("app.api.routes.collect_metadata", return_value=SAMPLE_DATA)
    await async_client.post("/metadata", json={"url": SAMPLE_URL})

    mock_task = mocker.patch("app.api.routes.asyncio.create_task")
    response = await async_client.get("/metadata", params={"url": SAMPLE_URL})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_get_metadata_not_found_returns_202(async_client, mocker: MockerFixture):
    """GET returns 202 and schedules background collection on cache miss."""
    def close_and_return_dummy_task(coro):
        coro.close()
        return mocker.MagicMock()

    mock_task = mocker.patch(
        "app.api.routes.asyncio.create_task",
        side_effect=close_and_return_dummy_task,
    )

    response = await async_client.get("/metadata", params={"url": SAMPLE_URL})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_get_metadata_pending_returns_202(async_client, mocker: MockerFixture):
    """GET returns 202 when pending record exists."""
    await mark_pending(SAMPLE_URL)
    mock_task = mocker.patch("app.api.routes.asyncio.create_task")

    response = await async_client.get("/metadata", params={"url": SAMPLE_URL})

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_get_metadata_failed_returns_200(async_client):
    """GET returns 200 when failed record exists."""
    await mark_failed(SAMPLE_URL, "Previous error")

    response = await async_client.get("/metadata", params={"url": SAMPLE_URL})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "Previous error"


@pytest.mark.asyncio
async def test_get_metadata_missing_url_param(async_client):
    """GET without a url query param returns 422."""
    response = await async_client.get("/metadata")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_metadata_invalid_url_returns_422(async_client):
    """GET with an invalid URL returns 422."""
    response = await async_client.get("/metadata", params={"url": "not-a-url"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_check(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_check(async_client):
    response = await async_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
