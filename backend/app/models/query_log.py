from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.database import Base


class QueryLog(Base):
    """
    I keep this table as a simple audit trail of RAG usage.
    It helps me show 'history' in the UI and also debug what users asked.
    """
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)