# I import models here so Alembic can discover them when autogenerating migrations.
# Without this, Alembic sometimes misses new tables.

from app.models.user import User
from app.models.document import Document
from app.models.profile import UserProfile, TechItem, UserStackItem