"""add uploaded_files table

Revision ID: 17176892b362
Revises: 6d6bf5ce51a3
Create Date: 2026-03-03 06:07:18.473557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '17176892b362'
down_revision: Union[str, Sequence[str], None] = '6d6bf5ce51a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # I want a proper audit trail for uploads:
    # - keep original filename + content type + size
    # - store the server storage path (where I saved it in /data/uploads)
    # - title/source are optional metadata used by RAG + UI
    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),

        # Optional: later we can connect this to auth (user_id).
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),

        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("uploaded_files")