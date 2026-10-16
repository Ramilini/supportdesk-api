from typing import Any

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.auth import router as auth_router
from app.api.v1.tickets import router as tickets_router

tags_metadata = [
    {
        "name": "Auth",
        "description": "Create a customer account and obtain a JWT access token.",
    },
    {
        "name": "Users",
        "description": "Read user profiles and manage user roles.",
    },
    {
        "name": "Tickets",
        "description": "Create, find, and update support tickets.",
    },
    {
        "name": "Comments",
        "description": "Add and read comments on accessible tickets.",
    },
    {
        "name": "System",
        "description": "Service health and infrastructure checks.",
    },
]

app = FastAPI(
    title="SupportDesk API",
    description=(
        "A role-aware customer support API for managing users, tickets, "
        "assignments, and ticket comments. Authenticate with a JWT Bearer "
        "token returned by `/auth/login`."
    ),
    version="1.0.0",
    openapi_tags=tags_metadata,
)
app.include_router(auth_router)
app.include_router(tickets_router)


@app.get(
    "/health",
    response_model=dict[str, str],
    tags=["System"],
    summary="Check API and database health",
    description="Runs a lightweight database query to verify connectivity.",
)
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=tags_metadata,
    )
    bearer_scheme = (
        openapi_schema.get("components", {})
        .get("securitySchemes", {})
        .get("BearerAuth")
    )
    if bearer_scheme is not None:
        bearer_scheme["bearerFormat"] = "JWT"

    app.openapi_schema = openapi_schema
    return openapi_schema


app.openapi = custom_openapi
