"""Add comments and ticket assignment.

Revision ID: 20261011_0005
Revises: 9b905a448acf
Create Date: 2026-10-11
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261011_0005"
down_revision: str | None = "9b905a448acf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(
            sa.Column("assigned_to_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tickets_assigned_to_id_users",
            "users",
            ["assigned_to_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tickets_assigned_to_id",
            ["assigned_to_id"],
            unique=False,
        )
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_id", "comments", ["id"], unique=False)
    op.create_index(
        "ix_comments_ticket_id",
        "comments",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_comments_author_id",
        "comments",
        ["author_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_comments_author_id", table_name="comments")
    op.drop_index("ix_comments_ticket_id", table_name="comments")
    op.drop_index("ix_comments_id", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_tickets_assigned_to_id", table_name="tickets")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint(
            "fk_tickets_assigned_to_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("assigned_to_id")
