"""Align the user role enum name and database default.

Revision ID: 20261006_0003
Revises: fd5731c72c44
Create Date: 2026-10-06
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261006_0003"
down_revision: str | None = "fd5731c72c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE userrole RENAME TO user_role_enum")
        op.execute(
            "ALTER TABLE users ALTER COLUMN role "
            "SET DEFAULT 'CUSTOMER'::user_role_enum"
        )
    else:
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "role",
                existing_type=sa.Enum(
                    "CUSTOMER",
                    "AGENT",
                    "ADMIN",
                    name="user_role_enum",
                ),
                existing_nullable=False,
                server_default=sa.text("'CUSTOMER'"),
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TYPE user_role_enum RENAME TO userrole")
    else:
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "role",
                existing_type=sa.Enum(
                    "CUSTOMER",
                    "AGENT",
                    "ADMIN",
                    name="user_role_enum",
                ),
                existing_nullable=False,
                server_default=None,
            )
