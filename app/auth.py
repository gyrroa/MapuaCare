import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from . import models, database
from .config import settings

# Password hashing (argon2 + bcrypt)
_pwd_ctx = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
)

def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return _pwd_ctx.verify(password, hashed)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")

def _now_utc() -> datetime:
    return datetime.utcnow()

def _hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)

def _create_refresh_jwt(user_id: int, jti: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = _now_utc() + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    payload = {"sub": str(user_id), "jti": jti, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

# --- DB helpers for refresh tokens ---
def issue_token_pair(db: Session, user_id: int) -> Tuple[str, str]:
    """Create access + refresh tokens and persist the refresh token (hashed)."""
    access = create_access_token({"sub": user_id})
    jti = uuid.uuid4().hex
    refresh = _create_refresh_jwt(user_id, jti)
    rec = models.RefreshToken(
        user_id=user_id,
        jti=jti,
        token_hash=_hash_token(refresh),
        expires_at=_now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        revoked=False,
    )
    db.add(rec)
    db.commit()
    return access, refresh

def _decode(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])

def verify_refresh_token(db: Session, token: str) -> models.RefreshToken:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = _decode(token)
        if payload.get("type") != "refresh":
            raise cred_exc
        jti = payload.get("jti")
        sub = payload.get("sub")
        if not jti or not sub:
            raise cred_exc
        user_id = int(sub)
    except Exception:
        raise cred_exc

    rec = db.query(models.RefreshToken).filter(models.RefreshToken.jti == jti).first()
    if not rec or rec.user_id != user_id:
        raise cred_exc
    if rec.revoked or rec.expires_at <= _now_utc():
        raise cred_exc
    if rec.token_hash != _hash_token(token):
        # hashed mismatch -> token tampering or DB desync
        raise cred_exc
    return rec

def rotate_refresh_token(db: Session, rec: models.RefreshToken) -> str:
    """Revoke the given record and issue a fresh refresh JWT, persisted."""
    rec.revoked = True
    new_jti = uuid.uuid4().hex
    new_token = _create_refresh_jwt(rec.user_id, new_jti)
    new_rec = models.RefreshToken(
        user_id=rec.user_id,
        jti=new_jti,
        token_hash=_hash_token(new_token),
        expires_at=_now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        revoked=False,
    )
    rec.replaced_by_jti = new_jti
    db.add(new_rec)
    db.commit()
    return new_token

def revoke_refresh_token(db: Session, token: str) -> None:
    """Revoke a refresh token (used for logout)."""
    try:
        payload = _decode(token)
        jti = payload.get("jti")
    except Exception:
        # If it's invalid/expired, treat as already revoked
        return
    rec = db.query(models.RefreshToken).filter(models.RefreshToken.jti == jti).first()
    if rec and not rec.revoked:
        rec.revoked = True
        db.commit()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = _decode(token)
        if payload.get("type") != "access":
            raise cred_exc
        user_id = payload.get("sub")
        if user_id is None:
            raise cred_exc
        user_id = int(user_id)
    except JWTError:
        raise cred_exc

    user = db.get(models.User, user_id)
    if not user:
        raise cred_exc
    return user
