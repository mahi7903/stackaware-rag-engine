# Expose Base at the package level so Alembic can import it as `from app.database import Base`.
from app.database.database import Base