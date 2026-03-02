from pydantic import BaseModel, EmailStr
from pydantic import BaseModel, EmailStr #for login

# Schema used when a new user registers.
# This defines the expected input structure for the registration API.
# I include full_name, email and password because those are the fields
# needed to create a new user account.
class UserRegister(BaseModel): #for register 
    full_name: str
    email: EmailStr
    password: str


# Schema returned after successful registration.
# I intentionally do NOT return the password or hashed password
# because sensitive credentials should never be exposed in API responses.
class UserResponse(BaseModel): # for register a user 
    id: int
    full_name: str
    email: EmailStr


class LoginRequest(BaseModel): #login schema
    email: EmailStr
    password: str


class TokenResponse(BaseModel): #jwttoken type for login
    access_token: str
    token_type: str = "bearer"


# --- Tech Stack schemas (user_stack_items) ---

class StackItemAdd(BaseModel):
    tech_slug: str
    version: str | None = None  # optional, user can skip


class StackItemOut(BaseModel):
    tech_slug: str
    tech_name: str
    category: str
    version: str | None = None

    class Config:
        from_attributes = True


#endpoint schema List available technologies (from tech_items)
class TechItemOut(BaseModel):
    slug: str
    name: str
    category: str

    class Config:
        from_attributes = True