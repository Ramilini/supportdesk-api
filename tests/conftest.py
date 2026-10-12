from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import Role, User


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_connection(db_engine) -> Generator[Connection, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(db_connection: Connection) -> Generator[Session, None, None]:
    test_session = sessionmaker(
        bind=db_connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )()
    try:
        yield test_session
    finally:
        test_session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    previous_override = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    def create_user(
        email: str,
        role: Role = Role.CUSTOMER,
        *,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password="unused",
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return create_user


@pytest.fixture
def headers_for() -> Callable[[str], dict[str, str]]:
    def make_headers(email: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {create_access_token(email)}",
        }

    return make_headers


@pytest.fixture
def customer_user(make_user: Callable[..., User]) -> User:
    return make_user("customer@example.com", Role.CUSTOMER)


@pytest.fixture
def agent_user(make_user: Callable[..., User]) -> User:
    return make_user("agent@example.com", Role.AGENT)


@pytest.fixture
def admin_user(make_user: Callable[..., User]) -> User:
    return make_user("admin@example.com", Role.ADMIN)


@pytest.fixture
def customer_headers(
    customer_user: User,
    headers_for: Callable[[str], dict[str, str]],
) -> dict[str, str]:
    return headers_for(customer_user.email)


@pytest.fixture
def agent_headers(
    agent_user: User,
    headers_for: Callable[[str], dict[str, str]],
) -> dict[str, str]:
    return headers_for(agent_user.email)


@pytest.fixture
def admin_headers(
    admin_user: User,
    headers_for: Callable[[str], dict[str, str]],
) -> dict[str, str]:
    return headers_for(admin_user.email)


@pytest.fixture
def make_ticket(db_session: Session) -> Callable[..., Ticket]:
    def create_ticket(
        owner: User,
        *,
        title: str = "Support request",
        description: str = "Please help.",
        status: TicketStatus = TicketStatus.OPEN,
        priority: TicketPriority = TicketPriority.MEDIUM,
    ) -> Ticket:
        ticket = Ticket(
            owner_id=owner.id,
            title=title,
            description=description,
            status=status,
            priority=priority,
        )
        db_session.add(ticket)
        db_session.flush()
        return ticket

    return create_ticket
