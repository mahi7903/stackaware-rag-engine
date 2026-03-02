from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base
from sqlalchemy.orm import relationship #for the file profile.py so SQLAlchemy links properly
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # One-to-one: user → profile (preferences/settings)
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
     # One-to-many: user → stack items (queryable technologies + versions)
    stack_items = relationship("UserStackItem", back_populates="user", cascade="all, delete-orphan")