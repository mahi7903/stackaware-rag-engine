"""add content_hash to uploaded_files

Revision ID: f5bd798da68e
Revises: 3623983ccf67
Create Date: 2026-03-04 06:00:47.086423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5bd798da68e'
down_revision: Union[str, Sequence[str], None] = '3623983ccf67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intent: store a stable hash so we can detect identical re-uploads and skip re-embedding.
    op.add_column("uploaded_files", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_uploaded_files_content_hash", "uploaded_files", ["content_hash"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_uploaded_files_content_hash", table_name="uploaded_files")
    op.drop_column("uploaded_files", "content_hash")