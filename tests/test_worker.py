import pytest
from pytest_mock import MockerFixture

from app.services.collector import CollectionError
from app.worker.tasks import collect_and_store


SAMPLE_URL = "https://example.com"
SAMPLE_DATA = {
    "headers": {"content-type": "text/html"},
    "cookies": {"session": "xyz"},
    "page_source": "<html></html>",
}


@pytest.mark.asyncio
async def test_collect_and_store_success(mocker: MockerFixture):
    """Successful collection writes completed record to DB."""
    mocker.patch(
        "app.worker.tasks.collect_metadata",
        return_value=SAMPLE_DATA,
    )
    mock_completed = mocker.patch(
        "app.worker.tasks.mark_completed", new_callable=mocker.AsyncMock
    )
    mock_failed = mocker.patch(
        "app.worker.tasks.mark_failed", new_callable=mocker.AsyncMock
    )

    await collect_and_store(SAMPLE_URL)

    mock_completed.assert_awaited_once_with(
        SAMPLE_URL,
        headers=SAMPLE_DATA["headers"],
        cookies=SAMPLE_DATA["cookies"],
        page_source=SAMPLE_DATA["page_source"],
    )
    mock_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_and_store_collection_error(mocker: MockerFixture):
    """CollectionError causes mark_failed to be called."""
    mocker.patch(
        "app.worker.tasks.collect_metadata",
        side_effect=CollectionError("network error"),
    )
    mock_failed = mocker.patch(
        "app.worker.tasks.mark_failed", new_callable=mocker.AsyncMock
    )

    await collect_and_store(SAMPLE_URL)

    mock_failed.assert_awaited_once_with(SAMPLE_URL, "network error")


@pytest.mark.asyncio
async def test_collect_and_store_does_not_raise(mocker: MockerFixture):
    """Task should never propagate unexpected exceptions to the caller."""
    mocker.patch(
        "app.worker.tasks.collect_metadata",
        side_effect=RuntimeError("surprise!"),
    )
    mocker.patch("app.worker.tasks.mark_failed", new_callable=mocker.AsyncMock)

    await collect_and_store(SAMPLE_URL)


@pytest.mark.asyncio
async def test_collect_and_store_handles_mark_failed_errors(mocker: MockerFixture):
    """mark_failed errors should not escape and crash the background task."""
    mocker.patch(
        "app.worker.tasks.collect_metadata",
        side_effect=CollectionError("network error"),
    )
    mock_failed = mocker.patch(
        "app.worker.tasks.mark_failed",
        new_callable=mocker.AsyncMock,
        side_effect=RuntimeError("db down"),
    )

    await collect_and_store(SAMPLE_URL)

    mock_failed.assert_awaited_once()
