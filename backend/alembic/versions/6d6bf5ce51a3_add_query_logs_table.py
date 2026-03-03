"""add query_logs table

Revision ID: 6d6bf5ce51a3
Revises: f1f09e344b04
Create Date: 2026-03-03 04:30:54.039595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6d6bf5ce51a3'
down_revision: Union[str, Sequence[str], None] = 'f1f09e344b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # I’m keeping this table simple + flexible:
    # - question/answer as TEXT
    # - sources as JSONB so we can store the exact list we returned to the user
    # - created_at for timeline + later analytics
    op.create_table(
        "query_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("query_logs")