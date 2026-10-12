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


def test_test_database_is_in_memory_and_distinct_from_application_database(
    db_session: Session,
) -> None:
    test_connection = db_session.get_bind()

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
