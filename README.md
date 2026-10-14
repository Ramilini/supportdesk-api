# SupportDesk API

A customer support ticket management REST API built with FastAPI and PostgreSQL.

## Tech Stack
- Python 3.11+
- FastAPI
- PostgreSQL
- SQLAlchemy 2.0
- Docker & Docker Compose
- pytest

## Setup Instructions
### Docker Compose

Copy `.env.example` to `.env` and set a strong, URL-safe PostgreSQL password and
a random `SECRET_KEY` of at least 32 characters. For example:

```sh
cp .env.example .env
openssl rand -hex 24
openssl rand -hex 32
```

Use the first generated value for `POSTGRES_PASSWORD` and the second for
`SECRET_KEY`. `.env` is ignored by Git and must not be committed.

Start PostgreSQL and the API:

```sh
docker compose up --build
```

The API waits for PostgreSQL's healthcheck, applies `alembic upgrade head`, and
then starts listening on port `8000`. The database data is stored in the named
`postgres_data` volume. The API's `/health` endpoint checks database
connectivity and is also used by the container healthcheck. Set `API_PORT` or
`POSTGRES_PORT` in `.env` to change the host ports.

### Integration tests

Run the complete test suite against the isolated `supportdesk_test` PostgreSQL
database using the Compose test profile:

```sh
docker compose --profile test run --build --rm test
```

The test profile starts a separate PostgreSQL service and named volume. Tests
create their schema from the application models and roll back an outer
transaction after each test. Running `pytest` locally without
`TEST_DATABASE_URL` continues to use an isolated in-memory SQLite database.

### Local development

To run the API outside Docker, set `DATABASE_URL` and `SECRET_KEY` in `.env`
before starting Uvicorn. Apply schema changes with `alembic upgrade head`.
`ALGORITHM` defaults to `HS256`, and `ACCESS_TOKEN_EXPIRE_MINUTES` defaults to
`60`. If no key is set for local development, a random key is generated at
startup; tokens will not remain valid after restarting the process.

Run the local test suite and print a per-file coverage report with:

```sh
pytest
```