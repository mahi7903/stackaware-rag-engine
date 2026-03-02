from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Flexible settings/preferences that can grow without schema churn.
    preferences = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="profile")


class TechItem(Base):
    __tablename__ = "tech_items"

    id = Column(Integer, primary_key=True, index=True)

    # Canonical key for analytics + de-duplication (e.g., "fastapi", "react", "postgresql").
    slug = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(150), nullable=False)

    # Keep it simple for v1: language/framework/database/cloud/tool/etc.
    category = Column(String(50), nullable=False, index=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    users = relationship("UserStackItem", back_populates="tech")


class UserStackItem(Base):
    __tablename__ = "user_stack_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tech_id = Column(Integer, ForeignKey("tech_items.id", ondelete="CASCADE"), nullable=False, index=True)

    # Optional version because it helps later analytics ("who is on FastAPI 0.110").
    version = Column(String(50), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="stack_items")
    tech = relationship("TechItem", back_populates="users")

    __table_args__ = (
        # Prevent duplicate tech rows per user (same tech added twice).
        UniqueConstraint("user_id", "tech_id", name="uq_user_tech"),
        Index("ix_user_stack_user_tech", "user_id", "tech_id"),
    )