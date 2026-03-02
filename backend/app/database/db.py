# This file provides a reusable database session dependency for FastAPI routes.
# I keep it separate so every endpoint uses the same clean pattern for opening
# and closing DB sessions safely.

from app.database.database import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()