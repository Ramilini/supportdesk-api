import os
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import engine as application_engine
from app.models.user import User


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_documents_bearer_authentication_and_operations(
    client: TestClient,
) -> None:
    assert client.get("/docs").status_code == 200
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "SupportDesk API"
    assert schema["info"]["version"] == "1.0.0"

    bearer_scheme = schema["components"]["securitySchemes"]["BearerAuth"]
    assert bearer_scheme["type"] == "http"
    assert bearer_scheme["scheme"] == "bearer"
    assert bearer_scheme["bearerFormat"] == "JWT"

    tags = {tag["name"] for tag in schema["tags"]}
    assert {"Auth", "Users", "Tickets", "Comments"} <= tags

    expected_operations = {
        ("/auth/register", "post"): ("Auth", "201", ("400",), False),
        ("/auth/login", "post"): ("Auth", "200", ("401",), False),
        ("/users/me", "get"): ("Users", "200", ("401",), True),
        ("/users/", "get"): ("Users", "200", ("401", "403"), True),
        ("/users/{user_id}/role", "patch"): (
            "Users",
            "200",
            ("401", "403", "404"),
            True,
        ),
        ("/tickets", "post"): ("Tickets", "201", ("401",), True),
        ("/tickets", "get"): ("Tickets", "200", ("401",), True),
        ("/tickets/{ticket_id}", "get"): (
            "Tickets",
            "200",
            ("401", "403", "404"),
            True,
        ),
        ("/tickets/{ticket_id}", "patch"): (
            "Tickets",
            "200",
            ("401", "403", "404"),
            True,
        ),
        ("/tickets/{ticket_id}/assign", "patch"): (
            "Tickets",
            "200",
            ("401", "403", "404", "422"),
            True,
        ),
        ("/tickets/{ticket_id}/comments", "post"): (
            "Comments",
            "201",
            ("401", "403", "404"),
            True,
        ),
        ("/tickets/{ticket_id}/comments", "get"): (
            "Comments",
            "200",
            ("401", "403", "404"),
            True,
        ),
        ("/health", "get"): ("System", "200", (), False),
    }
    for (path, method), (tag, success_status, error_statuses, protected) in (
        expected_operations.items()
    ):
        operation = schema["paths"][path][method]
        assert operation["tags"] == [tag]
        assert operation["summary"]
        assert operation["description"]
        assert "application/json" in operation["responses"][success_status]["content"]
        for error_status in error_statuses:
            assert error_status in operation["responses"]
        if protected:
            assert operation["security"] == [{"BearerAuth": []}]
        else:
            assert "security" not in operation


def test_test_database_is_isolated_from_application_database(
    db_session: Session,
) -> None:
    test_connection = db_session.get_bind()
    test_database_url = os.getenv("TEST_DATABASE_URL")

    if test_database_url:
        assert test_connection.dialect.name == "postgresql"
        assert test_connection.engine.url.database == "supportdesk_test"
    else:
        assert test_connection.dialect.name == "sqlite"
        assert test_connection.engine.url.database in (None, "")
    assert test_connection.engine is not application_engine


def test_database_dependency_closes_session_on_teardown(monkeypatch) -> None:
    session = Mock(spec=Session)
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(deps, "SessionLocal", session_factory)
    database_generator = deps.get_db()

    assert next(database_generator) is session
    database_generator.close()

    session.close.assert_called_once_with()


def test_database_commit_stays_inside_outer_rollback(
    db_connection,
    db_session: Session,
) -> None:
    user = User(email="transaction@example.com", hashed_password="unused")
    db_session.add(user)
    db_session.commit()

    assert db_connection.in_transaction()
    assert db_session.scalar(
        select(User).where(User.email == "transaction@example.com")
    ) is user
