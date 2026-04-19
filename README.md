# HTTP Metadata Inventory

A FastAPI service that collects and stores HTTP response headers, cookies, and page source for arbitrary URLs, backed by MongoDB.

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Run with Docker

```bash
docker-compose up --build
```

The API is available at **http://localhost:8000**.  
Interactive docs (Swagger UI) are available at **http://localhost:8000/docs**.

### Run Locally (for development)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the API
make run
# Or: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## API Reference

All endpoints accept and return JSON.

### `POST /metadata`

Immediately fetches and stores metadata for a URL.

**Request body**

```json
{ "url": "https://jiteshcodes.com" }
```

**Responses**

| Code | Meaning |
|------|---------|
| 201 | Metadata collected and stored (new URL or re-fetch) |
| 409 | Collection already in progress for this URL |
| 422 | Invalid URL |
| 429 | Rate limit exceeded |
| 502 | Failed to reach the target URL |
| 503 | Database not ready |
| 500 | Internal server error |

**Example**

```bash
curl -X POST http://localhost:8000/metadata \
     -H "Content-Type: application/json" \
     -d '{"url": "https://jiteshcodes.com"}'
```

---

### `GET /metadata?url=<url>`

Retrieves stored metadata for a URL.

**Responses**

| Code | Meaning |
|------|---------|
| 200 | Record found (completed or failed); full dataset returned |
| 202 | Record not found, collection scheduled; or collection pending |
| 422 | Invalid or missing `url` query parameter |
| 429 | Rate limit exceeded |
| 503 | Database not ready |

**Example**

```bash
curl "http://localhost:8000/metadata?url=https://jiteshcodes.com"
```

**Polling for background collection**

```bash
# First request - triggers background collection
curl "http://localhost:8000/metadata?url=https://httpbin.org/html"
# Returns 202 Accepted with status: "pending"

# Retry after a moment...
curl "http://localhost:8000/metadata?url=https://httpbin.org/html"
# Returns 200 OK with status: "completed"
```

---

### `GET /health`

Simple liveness probe. Returns `{"status": "ok"}`.

Used by orchestrators (Kubernetes, Docker) to check if the container is running.

---

### `GET /ready`

Readiness probe. Returns `{"status": "ready"}` when database is connected.

Used to ensure the service is ready to handle requests before routing traffic to it.

---

## Response Schema

```json
{
  "id": "507f1f77bcf86cd799439011",
  "url": "https://jiteshcodes.com",
  "status": "completed",
  "headers": { "content-type": "text/html" },
  "cookies": { "session": "abc123" },
  "page_source": "<!doctype html>...",
  "error": null,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:05Z"
}
```

`status` is one of:
- `pending` - Collection has been started
- `completed` - Metadata successfully collected
- `failed` - Collection failed (see `error` field)

---

## Running Tests

Tests use an in-memory MongoDB mock (`mongomock-motor`) — no real database required.

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
make test
# Or: pytest -v

# Run with coverage
make test-cov
# Or: pytest --cov=app --cov-report=term-missing
```

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make docker-up` | Start API and MongoDB with Docker |
| `make docker-down` | Stop Docker services |
| `make docker-logs` | View Docker logs |
| `make run` | Run API locally |
| `make test` | Run tests |
| `make test-cov` | Run tests with coverage |
| `make clean` | Remove containers and volumes |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | `mongodb://mongo:27017` | MongoDB connection string |
| `DATABASE_NAME` | `metadata_inventory` | Database name |
| `API_HOST` | `0.0.0.0` | Bind host |
| `API_PORT` | `8000` | Bind port |
| `REQUEST_TIMEOUT` | `30` | HTTP fetch timeout (seconds) |
| `MAX_PAGE_SOURCE_BYTES` | `14000000` | Max response body size allowed for stored page source |
| `USER_AGENT` | `Mozilla/5.0 (compatible; MetadataInventoryBot/1.0)` | User-Agent for fetches |
| `MONGODB_CONNECT_TIMEOUT` | `30` | Initial retry delay (seconds) |
| `MONGODB_CONNECT_RETRIES` | `3` | Max connection retry attempts |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `100` | Rate limit (per IP) |

---

## Architecture

### Layers

```
Client
  │
  ▼
FastAPI Routes (app/api/routes.py)
  │
  ├── Collector Service (app/services/collector.py)
  └── Background Worker (app/worker/tasks.py)
  │
  ▼
MongoDB (app/db/mongo.py)
```

### Background Collection

When `GET /metadata` finds no existing record:
1. Creates a `pending` record in MongoDB
2. Returns `202 Accepted` immediately
3. Schedules background task via `asyncio.create_task()`
4. Task runs independently, updating MongoDB on completion

### Rate Limiting

- Default: 100 requests per minute per IP address
- Uses SlowAPI library
- Configurable via `RATE_LIMIT_REQUESTS_PER_MINUTE`

---

## Production Considerations

- Uses `restart: unless-stopped` for automatic recovery
- Resource limits configured in docker-compose.yml
- Health checks for both API and MongoDB
- Graceful shutdown via FastAPI lifespan

---

## Tech Stack

- **Python 3.11+**: Core language
- **FastAPI**: Web framework
- **Motor**: Async MongoDB driver
- **MongoDB**: Document database
- **httpx**: Async HTTP client
- **slowapi**: Rate limiting
- **Pytest**: Testing framework
- **Docker Compose**: Container orchestration
