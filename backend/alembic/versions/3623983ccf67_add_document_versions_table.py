"""add document_versions table

Revision ID: 3623983ccf67
Revises: 17176892b362
Create Date: 2026-03-04 05:10:39.727722

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3623983ccf67'
down_revision: Union[str, Sequence[str], None] = '17176892b362'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intent:
    # We want clean version tracking separate from raw upload metadata.
    # uploaded_files = storage + filenames
    # document_versions = "logical document" + version history + which upload powers it

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),

        # stable identifier for "same logical doc" across replacements
        sa.Column("doc_key", sa.String(length=200), nullable=False),

        # monotonically increasing version number per doc_key
        sa.Column("version", sa.Integer(), nullable=False),

        # points to the physical upload that produced this version
        sa.Column("upload_id", sa.Integer(), nullable=False),

        # only one active version per doc_key
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),

        # optional metadata you might want later (safe + flexible)
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploaded_files.id"],
            name="fk_document_versions_upload_id_uploaded_files",
            ondelete="RESTRICT",
        ),
    )

    # Guarantee: cannot have two "v2" rows for the same doc_key
    op.create_index(
        "ux_document_versions_doc_key_version",
        "document_versions",
        ["doc_key", "version"],
        unique=True,
    )

    # Guarantee: only one active version per doc_key (Postgres partial unique index)
    op.create_index(
        "ux_document_versions_one_active_per_doc_key",
        "document_versions",
        ["doc_key"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # Link document chunks to a specific version (nullable for safe rollout / backfill later)
    op.add_column("documents", sa.Column("document_version_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_documents_document_version_id_document_versions",
        "documents",
        "document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_documents_document_version_id",
        "documents",
        ["document_version_id"],
        unique=False,
    )


def downgrade() -> None:
    # Rollback in reverse order (keeps DB consistent if we ever downgrade)
    op.drop_index("ix_documents_document_version_id", table_name="documents")
    op.drop_constraint(
        "fk_documents_document_version_id_document_versions",
        "documents",
        type_="foreignkey",
    )
    op.drop_column("documents", "document_version_id")

    op.drop_index("ux_document_versions_one_active_per_doc_key", table_name="document_versions")
    op.drop_index("ux_document_versions_doc_key_version", table_name="document_versions")
    op.drop_table("document_versions")