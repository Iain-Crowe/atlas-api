import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pwdlib import PasswordHash
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import User
from app.models import TokenPayload
from app.services.database import get_user_by_username

bearer_scheme = HTTPBearer()

password_hash = PasswordHash.recommended()
JWT_SECRET = os.environ["ATLAS_JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60

ROLE_LEVELS = {
    "admin": 3,
    "operator": 2,
    "viewer": 1,
}

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password,
    )

def create_access_token(username: str, role: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES)

    payload: dict[str, str | int] = {
        "sub": username,
        "role": role,
        "exp": int(expires_at.timestamp()),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )

        return TokenPayload.model_validate(payload)
    
    except (JWTError, ValidationError) as exc:
        raise ValueError("Invalid token") from exc

def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: Session = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token"
        )

    user = get_user_by_username(db, payload.sub)

    if not user:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token"
        )

    if not user.active:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token"
        )

    return user

def require_role(minimum_role: str):
    def dependency(
        current_user: User = Depends(get_current_user)
    ) -> User:
        user_level = ROLE_LEVELS.get(current_user.role)
        required_level = ROLE_LEVELS.get(minimum_role)

        if user_level is None or required_level is None:
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions"
            )

        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions"
            )

        return current_user
    
    return dependency
