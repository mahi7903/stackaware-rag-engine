from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.database import Base


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(Integer, primary_key=True, index=True)

    # Intent: stable key for "same logical document" (used to group versions)
    doc_key = Column(String(200), nullable=False, index=True)

    # Intent: monotonically increasing version per doc_key
    version = Column(Integer, nullable=False)

    # Intent: points to the physical upload row that produced this version
    upload_id = Column(Integer, ForeignKey("uploaded_files.id", ondelete="RESTRICT"), nullable=False)

    # Intent: only one active version per doc_key (DB enforces via partial unique index)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    # Intent: keep it flexible (we can store extra debug info later if needed)
    meta = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # Relationships (nice for joins in future endpoints)
    documents = relationship("Document", back_populates="document_version")