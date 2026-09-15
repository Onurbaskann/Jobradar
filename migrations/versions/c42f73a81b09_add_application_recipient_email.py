"""add application recipient email

Revision ID: c42f73a81b09
Revises: e2f319a70644
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c42f73a81b09"
down_revision: str | None = "e2f319a70644"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application",
        sa.Column("recipient_email", sa.String(), server_default="", nullable=False),
    )
    op.alter_column("application", "recipient_email", server_default=None)


def downgrade() -> None:
    op.drop_column("application", "recipient_email")
