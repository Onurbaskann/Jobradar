"""add match queue and original CV filename

Revision ID: f31a7c9d2401
Revises: c42f73a81b09
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f31a7c9d2401"
down_revision: str | None = "c42f73a81b09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("profile", sa.Column("cv_original_filename", sa.String(), nullable=True))
    op.create_table(
        "match_queue_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["job_lead.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "lead_id", "profile_id", name="uq_match_queue_run_lead"),
    )
    op.create_index(op.f("ix_match_queue_item_run_id"), "match_queue_item", ["run_id"])
    op.create_index(op.f("ix_match_queue_item_lead_id"), "match_queue_item", ["lead_id"])
    op.create_index(op.f("ix_match_queue_item_profile_id"), "match_queue_item", ["profile_id"])
    op.create_index(op.f("ix_match_queue_item_status"), "match_queue_item", ["status"])
    op.create_index(op.f("ix_match_queue_item_created_at"), "match_queue_item", ["created_at"])


def downgrade() -> None:
    op.drop_table("match_queue_item")
    op.drop_column("profile", "cv_original_filename")
