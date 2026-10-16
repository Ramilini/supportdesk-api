from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models.comment import Comment
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import Role, User
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.ticket import (
    TicketAssignment,
    TicketCreate,
    TicketResponse,
    TicketUpdate,
)

router = APIRouter(prefix="/tickets")

UNAUTHORIZED_RESPONSE = {
    "description": "The request is unauthenticated or the token is invalid.",
}
FORBIDDEN_RESPONSE = {
    "description": "The authenticated user does not have permission.",
}
TICKET_NOT_FOUND_RESPONSE = {"description": "The requested ticket does not exist."}


def _get_accessible_ticket(
    ticket_id: int,
    db: Session,
    current_user: User,
) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )
    if current_user.role is Role.CUSTOMER and ticket.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers can only access their own tickets",
        )
    return ticket


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tickets"],
    summary="Create a support ticket",
    description="Creates a ticket owned by the authenticated user.",
    responses={status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE},
)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    ticket = Ticket(**payload.model_dump(), owner_id=current_user.id)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post(
    "/{ticket_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Comments"],
    summary="Add a comment to a ticket",
    description="Adds a comment authored by the authenticated user.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: TICKET_NOT_FOUND_RESPONSE,
    },
)
def create_comment(
    ticket_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    ticket = _get_accessible_ticket(ticket_id, db, current_user)
    comment = Comment(
        ticket_id=ticket.id,
        author_id=current_user.id,
        content=payload.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get(
    "/{ticket_id}/comments",
    response_model=list[CommentResponse],
    tags=["Comments"],
    summary="List ticket comments",
    description="Returns comments in creation order for an accessible ticket.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: TICKET_NOT_FOUND_RESPONSE,
    },
)
def list_comments(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Comment]:
    ticket = _get_accessible_ticket(ticket_id, db, current_user)
    query = (
        select(Comment)
        .where(Comment.ticket_id == ticket.id)
        .order_by(Comment.id)
    )
    return list(db.scalars(query).all())


@router.patch(
    "/{ticket_id}/assign",
    response_model=TicketResponse,
    tags=["Tickets"],
    summary="Assign or unassign a ticket",
    description=(
        "Assigns a ticket to an active agent, or clears the assignment when "
        "`assigned_to_id` is null. Available to agents and administrators."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: {
            "description": "The ticket or requested agent does not exist.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "The assignee is not an active agent.",
        },
    },
)
def assign_ticket(
    ticket_id: int,
    payload: TicketAssignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(Role.AGENT, Role.ADMIN)),
) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    if payload.assigned_to_id is None:
        ticket.assigned_to_id = None
    else:
        agent = db.get(User, payload.assigned_to_id)
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )
        if agent.role is not Role.AGENT or not agent.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Assignee must be an active agent",
            )
        ticket.assigned_to_id = agent.id

    db.commit()
    db.refresh(ticket)
    return ticket


@router.get(
    "",
    response_model=list[TicketResponse],
    tags=["Tickets"],
    summary="List tickets",
    description=(
        "Returns tickets in ID order with optional status, priority, and "
        "pagination filters. Customers see only their own tickets."
    ),
    responses={status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE},
)
def list_tickets(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    ticket_status: TicketStatus | None = Query(default=None, alias="status"),
    priority: TicketPriority | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Ticket]:
    query = select(Ticket)
    if current_user.role is Role.CUSTOMER:
        query = query.where(Ticket.owner_id == current_user.id)
    if ticket_status is not None:
        query = query.where(Ticket.status == ticket_status)
    if priority is not None:
        query = query.where(Ticket.priority == priority)

    query = query.order_by(Ticket.id).offset(skip).limit(limit)
    return list(db.scalars(query).all())


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    tags=["Tickets"],
    summary="Get a ticket",
    description="Returns a ticket the authenticated user is allowed to access.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: TICKET_NOT_FOUND_RESPONSE,
    },
)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    return _get_accessible_ticket(ticket_id, db, current_user)


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    tags=["Tickets"],
    summary="Update a ticket",
    description=(
        "Updates ticket fields. Customers may update an open ticket and may "
        "only close it; agents and administrators can update any accessible ticket."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: TICKET_NOT_FOUND_RESPONSE,
    },
)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    ticket = _get_accessible_ticket(ticket_id, db, current_user)

    updates = payload.model_dump(exclude_unset=True)
    if current_user.role is Role.CUSTOMER:
        if ticket.status is not TicketStatus.OPEN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only update open tickets",
            )
        if (
            "status" in updates
            and updates["status"] is not TicketStatus.CLOSED
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers may only close their tickets",
            )

    for field, value in updates.items():
        setattr(ticket, field, value)
    db.commit()
    db.refresh(ticket)
    return ticket
