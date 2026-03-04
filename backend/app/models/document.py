from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from sqlalchemy import Column, Integer, Text
from pgvector.sqlalchemy import Vector #embeddig import

#version document table imports
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source = Column(Text, nullable=True)        # for eg fastapi_notes.tx/any othe ifle "
    chunk_index = Column(Integer, nullable=True)  # 0..N-1
    chunk_count = Column(Integer, nullable=True)  # N
    embedding = Column(Vector(1536), nullable=True) #embedding column
        # Intent: link every embedded chunk to the exact document version that created it
    document_version_id = Column(
        Integer,
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    document_version = relationship("DocumentVersion", back_populates="documents")