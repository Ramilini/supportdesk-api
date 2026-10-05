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
Set `DATABASE_URL` and `SECRET_KEY` in an ignored `.env` file before starting the API.
`SECRET_KEY` must be at least 32 characters; `ALGORITHM` defaults to `HS256`, and
`ACCESS_TOKEN_EXPIRE_MINUTES` defaults to `60`. A random key is generated when
`SECRET_KEY` is not set, which is suitable only for local development because
tokens will no longer validate after a restart.

Apply the database schema with Alembic before running the API:

```shell
alembic upgrade head
```