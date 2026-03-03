from sqlalchemy import Column, Integer, Text, DateTime, BigInteger
from sqlalchemy.sql import func

from app.database.database import Base


class UploadedFile(Base):
    """
    I store upload metadata here so I can:
     show an admin "Uploads" page later
     track what docs were added, when, and from which filename
    keep a reliable pointer to the saved file path on disk
    """
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)

    original_filename = Column(Text, nullable=False)
    stored_filename = Column(Text, nullable=False)

    content_type = Column(Text, nullable=True)
    size_bytes = Column(BigInteger, nullable=False)

    title = Column(Text, nullable=True)
    source = Column(Text, nullable=True)

    storage_path = Column(Text, nullable=False)

    # Keeping it nullable for now. Later we can connect it to auth user_id.
    uploaded_by_user_id = Column(Integer, nullable=True)

    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)