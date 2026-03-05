"""add user_id to query_logs

Revision ID: 5fc7ef65c9a0
Revises: f5bd798da68e
Create Date: 2026-03-04 07:21:38.380675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fc7ef65c9a0'
down_revision: Union[str, Sequence[str], None] = 'f5bd798da68e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    # Intent: link each RAG query to the user who made it (needed for per-user history).
    op.add_column("query_logs", sa.Column("user_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_query_logs_user_id_users",
        "query_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_query_logs_user_id", table_name="query_logs")
    op.drop_constraint("fk_query_logs_user_id_users", "query_logs", type_="foreignkey")
    op.drop_column("query_logs", "user_id")
