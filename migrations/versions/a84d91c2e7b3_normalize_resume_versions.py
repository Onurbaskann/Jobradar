"""normalize resume versions and ATS assessment

Revision ID: a84d91c2e7b3
Revises: f31a7c9d2401
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a84d91c2e7b3"
down_revision: str | None = "f31a7c9d2401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _resume_child_table(name: str, *columns: sa.Column) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        *columns,
        sa.ForeignKeyConstraint(["resume_id"], ["resume.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f(f"ix_{name}_resume_id"), name, ["resume_id"])


def upgrade() -> None:
    op.create_table(
        "resume",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("extracted_text", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("linkedin_url", sa.String(), nullable=True),
        sa.Column("github_url", sa.String(), nullable=True),
        sa.Column("portfolio_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("extraction_model", sa.String(), nullable=True),
        sa.Column("processing_error", sa.String(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "sha256", name="uq_resume_profile_hash"),
        sa.UniqueConstraint("profile_id", "version", name="uq_resume_profile_version"),
    )
    for column in ("profile_id", "sha256", "status", "uploaded_at"):
        op.create_index(op.f(f"ix_resume_{column}"), "resume", [column])

    _resume_child_table(
        "resume_experience",
        sa.Column("employer", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("start_month", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("end_month", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    _resume_child_table(
        "resume_education",
        sa.Column("institution", sa.String(), nullable=False),
        sa.Column("degree", sa.String(), nullable=True),
        sa.Column("field_of_study", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("start_month", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("end_month", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    _resume_child_table(
        "resume_project",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("start_month", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("end_month", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    _resume_child_table(
        "resume_skill",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("evidence", sa.String(), nullable=False),
        sa.UniqueConstraint("resume_id", "normalized_name", name="uq_resume_skill_name"),
    )
    _resume_child_table(
        "resume_certification",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=True),
        sa.Column("issue_year", sa.Integer(), nullable=True),
        sa.Column("issue_month", sa.Integer(), nullable=True),
        sa.Column("expiry_year", sa.Integer(), nullable=True),
        sa.Column("expiry_month", sa.Integer(), nullable=True),
        sa.Column("credential_id", sa.String(), nullable=True),
        sa.Column("credential_url", sa.String(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    _resume_child_table(
        "resume_language",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("level", sa.String(), nullable=True),
        sa.UniqueConstraint("resume_id", "normalized_name", name="uq_resume_language_name"),
    )
    _resume_child_table(
        "resume_assessment",
        sa.Column("rubric_version", sa.String(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("parsing_score", sa.Integer(), nullable=False),
        sa.Column("contact_score", sa.Integer(), nullable=False),
        sa.Column("section_score", sa.Integer(), nullable=False),
        sa.Column("chronology_score", sa.Integer(), nullable=False),
        sa.Column("evidence_score", sa.Integer(), nullable=False),
        sa.Column("consistency_score", sa.Integer(), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assessed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "resume_id", "rubric_version", name="uq_resume_assessment_rubric"
        ),
    )

    op.execute(
        """
        INSERT INTO resume (
            profile_id, version, original_filename, file_path, sha256, mime_type,
            extracted_text, language, summary, status, parser_version, uploaded_at
        )
        SELECT id, 1,
            COALESCE(cv_original_filename, 'candidate-cv'),
            cv_file_path,
            NULL,
            CASE
                WHEN lower(cv_file_path) LIKE '%.pdf' THEN 'application/pdf'
                WHEN lower(cv_file_path) LIKE '%.docx' THEN
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                ELSE 'text/plain'
            END,
            cv_text, NULL, COALESCE(cv_summary, ''), 'pending', '1', updated_at
        FROM profile
        WHERE cv_file_path IS NOT NULL AND COALESCE(cv_text, '') <> ''
        """
    )

    op.add_column("lead_match", sa.Column("resume_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_lead_match_resume", "lead_match", "resume", ["resume_id"], ["id"])
    op.create_index(op.f("ix_lead_match_resume_id"), "lead_match", ["resume_id"])
    op.execute(
        "UPDATE lead_match SET resume_id = resume.id FROM resume "
        "WHERE resume.profile_id = lead_match.profile_id"
    )
    op.drop_constraint("uq_lead_match_profile", "lead_match", type_="unique")
    op.create_unique_constraint("uq_lead_match_resume", "lead_match", ["lead_id", "resume_id"])

    op.add_column("match_queue_item", sa.Column("resume_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_match_queue_resume", "match_queue_item", "resume", ["resume_id"], ["id"]
    )
    op.create_index(op.f("ix_match_queue_item_resume_id"), "match_queue_item", ["resume_id"])
    op.execute(
        "UPDATE match_queue_item SET resume_id = resume.id FROM resume "
        "WHERE resume.profile_id = match_queue_item.profile_id"
    )
    op.drop_constraint("uq_match_queue_run_lead", "match_queue_item", type_="unique")
    op.create_unique_constraint(
        "uq_match_queue_run_lead",
        "match_queue_item",
        ["run_id", "lead_id", "resume_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_match_queue_run_lead", "match_queue_item", type_="unique")
    op.create_unique_constraint(
        "uq_match_queue_run_lead",
        "match_queue_item",
        ["run_id", "lead_id", "profile_id"],
    )
    op.drop_index(op.f("ix_match_queue_item_resume_id"), table_name="match_queue_item")
    op.drop_constraint("fk_match_queue_resume", "match_queue_item", type_="foreignkey")
    op.drop_column("match_queue_item", "resume_id")

    op.drop_constraint("uq_lead_match_resume", "lead_match", type_="unique")
    op.create_unique_constraint("uq_lead_match_profile", "lead_match", ["lead_id", "profile_id"])
    op.drop_index(op.f("ix_lead_match_resume_id"), table_name="lead_match")
    op.drop_constraint("fk_lead_match_resume", "lead_match", type_="foreignkey")
    op.drop_column("lead_match", "resume_id")

    for table in (
        "resume_assessment",
        "resume_language",
        "resume_certification",
        "resume_skill",
        "resume_project",
        "resume_education",
        "resume_experience",
    ):
        op.drop_table(table)
    op.drop_table("resume")
