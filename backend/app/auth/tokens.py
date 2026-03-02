import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import jwt
#to authorize token intead of http in the swagger
from fastapi.security import OAuth2PasswordBearer 
from fastapi import Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.user import User

# Keeping token creation/verification separate from password hashing makes auth easier to maintain.
# security.py = passwords, tokens.py = JWT handling.

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # must be set in .env
# Used by FastAPI docs to show the "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(
    subject: str,
    expires_minutes: int = 60,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """
    Create a signed JWT.

    subject: typically the user id or email using user id
    expires_minutes: default 60 minutes.
    extra_claims: optional extra payload fields.
    """
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not set in environment/.env")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes)

    payload: dict[str, Any] = {"sub": subject, "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


#to get and to decode the token 
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # Decode token, then fetch the user from DB. Keeps auth checks consistent across endpoints.
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    user = db.query(User).filter(User.id == int(sub)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user