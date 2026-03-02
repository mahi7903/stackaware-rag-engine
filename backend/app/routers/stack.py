from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.auth.tokens import get_current_user
from app.schemas.schemas import StackItemAdd, StackItemOut, TechItemOut
from app.models.profile import TechItem, UserStackItem, UserProfile

router = APIRouter()


@router.post("/items", response_model=StackItemOut, status_code=status.HTTP_201_CREATED)
def add_stack_item(
    payload: StackItemAdd,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) find the tech by slug (frontend-friendly)
    tech = db.query(TechItem).filter(TechItem.slug == payload.tech_slug).first()
    if not tech:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tech item not found. Use a valid tech_slug.",
        )

    # 2) block duplicates (db also enforces unique constraint, but we give a nice message)
    existing = (
        db.query(UserStackItem)
        .filter(
            UserStackItem.user_id == current_user.id,
            UserStackItem.tech_id == tech.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That tech is already in your stack.",
        )

    # 3) create stack item
    stack_item = UserStackItem(
        user_id=current_user.id,
        tech_id=tech.id,
        version=payload.version,
    )
    db.add(stack_item)
    db.commit()
    db.refresh(stack_item)
        # --- mirror stack into user profile preferences (JSONB) ---
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if not profile:
        # create profile if missing (keeps UX smooth)
        profile = UserProfile(user_id=current_user.id, preferences={})
        db.add(profile)
        db.commit()
        db.refresh(profile)


    # 4) store the profile
    prefs = profile.preferences or {}
    stack_list = prefs.get("stack", [])

    stack_list.append(
        {
            "tech_slug": tech.slug,
            "version": payload.version,
        }
    )

    prefs["stack"] = stack_list
    profile.preferences = prefs
    db.commit()

    # 5) return a clean response (don’t leak internal IDs)
    return StackItemOut(
        tech_slug=tech.slug,
        tech_name=tech.name,
        category=tech.category,
        version=stack_item.version,
    )


@router.get("/my", response_model=list[StackItemOut])
def get_my_stack(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile or not profile.preferences:
        return []

    stack_list = (profile.preferences or {}).get("stack", [])
    if not stack_list:
        return []

    results: list[StackItemOut] = []

    for item in stack_list:
        tech_slug = item.get("tech_slug")
        version = item.get("version")

        if not tech_slug:
            continue

        tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()
        if not tech:
            # if tech was removed from catalog, we just skip it
            continue

        results.append(
            StackItemOut(
                tech_slug=tech.slug,
                tech_name=tech.name,
                category=tech.category,
                version=version,
            )
        )

    return results

#route to delete the slug
@router.delete("/items/{tech_slug}", status_code=204)
def remove_stack_item(
    tech_slug: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # find tech in catalog
    tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()
    if not tech:
        raise HTTPException(status_code=404, detail="Tech not found")

    # remove relational entry
    stack_item = (
        db.query(UserStackItem)
        .filter(
            UserStackItem.user_id == current_user.id,
            UserStackItem.tech_id == tech.id,
        )
        .first()
    )

    if not stack_item:
        raise HTTPException(status_code=404, detail="Tech not in your stack")

    db.delete(stack_item)
    db.commit()

    # update profile mirror
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if profile and profile.preferences:
        prefs = profile.preferences
        stack_list = prefs.get("stack", [])

        stack_list = [item for item in stack_list if item.get("tech_slug") != tech_slug]

        prefs["stack"] = stack_list
        profile.preferences = prefs
        db.commit()

    return


#route to list the slug 
@router.get("/tech", response_model=list[TechItemOut])
def list_tech_catalog(db: Session = Depends(get_db)):
    # simple catalog list for dropdowns/search in frontend
    items = db.query(TechItem).order_by(TechItem.category.asc(), TechItem.name.asc()).all()
    return items