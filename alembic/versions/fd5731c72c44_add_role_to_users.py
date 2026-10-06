"""add_role_to_users

Revision ID: fd5731c72c44
Revises: 20261006_0002
Create Date: 2026-10-06 19:16:04.288558

"""
from typing import Sequence, Union

revision: str = 'fd5731c72c44'
down_revision: Union[str, Sequence[str], None] = '20261006_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
