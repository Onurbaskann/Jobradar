"""link applications to lead matches

Revision ID: e2f319a70644
Revises: b6c1a4d92e30
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f319a70644"
down_revision: str | None = "b6c1a4d92e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("application_match_id_fkey", "application", type_="foreignkey")
    op.drop_index(op.f("ix_application_match_id"), table_name="application")
    op.alter_column("application", "match_id", new_column_name="lead_match_id")
    op.alter_column("application", "lead_match_id", nullable=True)
    op.add_column(
        "application",
        sa.Column("job_title", sa.String(), server_default="", nullable=False),
    )
    op.add_column(
        "application",
        sa.Column("company_name", sa.String(), server_default="", nullable=False),
    )
    op.alter_column("application", "job_title", server_default=None)
    op.alter_column("application", "company_name", server_default=None)
    op.create_foreign_key(
        "application_lead_match_id_fkey",
        "application",
        "lead_match",
        ["lead_match_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_application_lead_match_id"),
        "application",
        ["lead_match_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_application_lead_match_id"), table_name="application")
    op.drop_constraint("application_lead_match_id_fkey", "application", type_="foreignkey")
    op.drop_column("application", "company_name")
    op.drop_column("application", "job_title")
    op.alter_column("application", "lead_match_id", new_column_name="match_id")
    op.alter_column("application", "match_id", nullable=False)
    op.create_foreign_key(
        "application_match_id_fkey",
        "application",
        "match",
        ["match_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_application_match_id"), "application", ["match_id"], unique=True
    )
