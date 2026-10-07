"""Create tickets table.

Revision ID: 20261007_0004
Revises: 20261006_0003
Create Date: 2026-10-07
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261007_0004"
down_revision: str | None = "20261006_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ticket_status_enum = sa.Enum(
    "OPEN",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
    name="ticket_status_enum",
)
ticket_priority_enum = sa.Enum(
    "LOW",
    "MEDIUM",
    "HIGH",
    "URGENT",
    name="ticket_priority_enum",
)


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            ticket_status_enum,
            server_default=sa.text("'OPEN'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            ticket_priority_enum,
            server_default=sa.text("'MEDIUM'"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_id", "tickets", ["id"], unique=False)
    op.create_index(
        "ix_tickets_owner_id", "tickets", ["owner_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_owner_id", table_name="tickets")
    op.drop_index("ix_tickets_id", table_name="tickets")
    op.drop_table("tickets")
    if op.get_bind().dialect.name == "postgresql":
        ticket_priority_enum.drop(op.get_bind(), checkfirst=True)
        ticket_status_enum.drop(op.get_bind(), checkfirst=True)
