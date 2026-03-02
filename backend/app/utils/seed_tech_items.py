# seed_tech_items.py
# purpose: populate the tech_items table with initial technologies
# this helps the system track developer stacks later

from app.database.database import SessionLocal
from app.models.profile import TechItem

def make_slug(name: str) -> str:
    # quick, readable slug maker for seeding
    return name.strip().lower().replace(" ", "-").replace(".", "")
def seed_tech_items():
    db = SessionLocal()

    # initial technology list for the platform
    tech_list = [
    {"name": "React", "category": "frontend"},
    {"name": "FastAPI", "category": "backend"},
    {"name": "PostgreSQL", "category": "database"},
    {"name": "Docker", "category": "devops"},
    {"name": "Python", "category": "language"},
    {"name": "Node.js", "category": "backend"},
    {"name": "Redis", "category": "database"},
    {"name": "Kubernetes", "category": "devops"},
    ]

    for tech in tech_list:
        # check if tech already exists to avoid duplicates
        slug = make_slug(tech["name"])
        existing = db.query(TechItem).filter(TechItem.slug == slug).first()

        if not existing:
            new_tech = TechItem(
            slug=slug,
            name=tech["name"],
            category=tech["category"],
            )
            db.add(new_tech)

    db.commit()
    db.close()

    print("tech items seeded successfully")


if __name__ == "__main__":
    seed_tech_items()