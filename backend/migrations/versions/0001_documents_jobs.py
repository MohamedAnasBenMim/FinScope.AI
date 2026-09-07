"""Durable document metadata and ingestion queue."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(100), unique=True, nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("extension", sa.String(10), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("dedup_key", sa.String(64), unique=True),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("classification_confidence", sa.Float, nullable=False),
        sa.Column("page_count", sa.Integer),
        sa.Column("extraction_metadata", sa.JSON, nullable=False),
        sa.Column("structured_data", sa.JSON, nullable=False),
        sa.Column("normalized_data", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("checksum", "status", "document_type"):
        op.create_index(f"ix_documents_{column}", "documents", [column])
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("error", sa.String(1000)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("document_id", "status"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])
    op.create_index("ix_jobs_status_created", "ingestion_jobs", ["status", "created_at"])


def downgrade():
    op.drop_table("ingestion_jobs")
    op.drop_table("documents")
