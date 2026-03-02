from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    # DEBUG: checking what value we are actually hashing
    print("DEBUG password type:", type(password))
    print("DEBUG password length:", len(password))
    print("DEBUG password preview:", str(password)[:60])

    return pwd_context.hash(password)
    


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)