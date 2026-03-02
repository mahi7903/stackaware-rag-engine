from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.user import User
from app.schemas.schemas import UserRegister, UserResponse
from app.auth.security import hash_password

#imports for logins now 
import os

from app.auth.security import verify_password
from app.auth.tokens import create_access_token
from app.schemas.schemas import LoginRequest, TokenResponse
from fastapi.security import OAuth2PasswordRequestForm
# import to get token sent n decoded with Oauthbearertoken
from app.auth.tokens import get_current_user

router = APIRouter(tags=["auth"])


#JWT endpoint to verify token route
@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    # Quick sanity endpoint: proves the JWT works and returns the logged-in user's safe profile.
    return current_user



#register route
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED,)
def register_user(payload: UserRegister, db: Session = Depends(get_db)):
    # Check if the email already exists — prevents duplicate accounts.
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    # Hash the password before saving — never store raw passwords.
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user



#login route 
@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Swagger's Authorize uses OAuth2 "password" flow, so we accept form fields here.
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    token = create_access_token(subject=str(user.id), expires_minutes=expire_minutes)

    return {"access_token": token, "token_type": "bearer"}