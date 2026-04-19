import pytest
import httpx
from pytest_mock import MockerFixture

from app.services.collector import CollectionError, collect_metadata


SAMPLE_URL = "https://example.com"


async def _iter_chunks(chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_collect_metadata_success(mocker: MockerFixture):
    """Happy-path: returns headers, cookies, and page_source."""
    mock_response = mocker.MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.cookies = {"session": "abc123"}
    mock_response.encoding = "utf-8"
    mock_response.status_code = 200
    mock_response.aiter_bytes = lambda: _iter_chunks([b"<html>Hello</html>"])

    stream_context = mocker.AsyncMock()
    stream_context.__aenter__ = mocker.AsyncMock(return_value=mock_response)
    stream_context.__aexit__ = mocker.AsyncMock(return_value=False)

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.stream = mocker.MagicMock(return_value=stream_context)

    mocker.patch("app.services.collector.httpx.AsyncClient", return_value=mock_client)

    result = await collect_metadata(SAMPLE_URL)

    assert result["headers"] == {"content-type": "text/html"}
    assert result["cookies"] == {"session": "abc123"}
    assert result["page_source"] == "<html>Hello</html>"


@pytest.mark.asyncio
async def test_collect_metadata_timeout(mocker: MockerFixture):
    """TimeoutException is wrapped in CollectionError."""
    stream_context = mocker.AsyncMock()
    stream_context.__aenter__ = mocker.AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )
    stream_context.__aexit__ = mocker.AsyncMock(return_value=False)

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.stream = mocker.MagicMock(return_value=stream_context)

    mocker.patch("app.services.collector.httpx.AsyncClient", return_value=mock_client)

    with pytest.raises(CollectionError, match="timed out"):
        await collect_metadata(SAMPLE_URL)


@pytest.mark.asyncio
async def test_collect_metadata_request_error(mocker: MockerFixture):
    """Network RequestError is wrapped in CollectionError."""
    stream_context = mocker.AsyncMock()
    stream_context.__aenter__ = mocker.AsyncMock(
        side_effect=httpx.RequestError("connection refused")
    )
    stream_context.__aexit__ = mocker.AsyncMock(return_value=False)

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.stream = mocker.MagicMock(return_value=stream_context)

    mocker.patch("app.services.collector.httpx.AsyncClient", return_value=mock_client)

    with pytest.raises(CollectionError, match="connection refused"):
        await collect_metadata(SAMPLE_URL)


@pytest.mark.asyncio
async def test_collect_metadata_rejects_oversized_body(mocker: MockerFixture):
    """Oversized response bodies are rejected before persistence."""
    mocker.patch("app.services.collector.settings.max_page_source_bytes", 10)

    mock_response = mocker.MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.cookies = {}
    mock_response.encoding = "utf-8"
    mock_response.status_code = 200
    mock_response.aiter_bytes = lambda: _iter_chunks([b"0123456789ABCDEF"])

    stream_context = mocker.AsyncMock()
    stream_context.__aenter__ = mocker.AsyncMock(return_value=mock_response)
    stream_context.__aexit__ = mocker.AsyncMock(return_value=False)

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.stream = mocker.MagicMock(return_value=stream_context)

    mocker.patch("app.services.collector.httpx.AsyncClient", return_value=mock_client)

    with pytest.raises(CollectionError, match="too large"):
        await collect_metadata(SAMPLE_URL)
