from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import os
from pydantic import BaseModel

# --- THIS IS THE FIX ---
# We are importing bcrypt directly
import bcrypt
# --- END OF FIX ---

from . import models, schemas
from .database import get_db

# --- 1. Password Hashing (REMOVED PASSLIB) ---
# We no longer need pwd_context

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a hashed one using bcrypt."""
    try:
        # Encode both to bytes for bcrypt
        plain_password_bytes = plain_password.encode('utf-8')
        hashed_password_bytes = hashed_password.encode('utf-8')
        
        # Check the password
        return bcrypt.checkpw(plain_password_bytes, hashed_password_bytes)
    except Exception:
        # Fails on invalid hash format, etc.
        return False

def get_password_hash(password: str) -> str:
    """Hashes a plain password using bcrypt."""
    # Need to encode password to bytes for bcrypt
    password_bytes = password.encode('utf-8')
    # Generate a salt and hash the password
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    # Decode back to string to store in DB
    return hashed_bytes.decode('utf-8')

# --- 2. JWT Token Configuration ---
SECRET_KEY = os.getenv("SECRET_KEY", "a_very_secret_key_that_you_should_change")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")

# --- 3. User Authentication ---
def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    """Finds a user by email and verifies their password."""
    user = db.scalar(select(models.User).where(models.User.email == email))
    if not user:
        return None
    # This will now call our new bcrypt verify_password function
    if not verify_password(password, user.hashed_password):
        return None
    return user

# --- 4. Token Creation ---
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

# --- vvv THIS IS THE NEW CLASS vvv ---
# This new schema matches what your frontend (src/features/auth/api.ts) expects
class LoginResponse(Token):
    user: schemas.UserRead
# --- ^^^ THIS IS THE NEW CLASS ^^^ ---


def _create_token(data: dict, expires_delta: timedelta) -> str:
    """Helper to create a JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_access_and_refresh_tokens(user: models.User, db: Session) -> Token:
    """Creates both an access token and a refresh token for the user."""
    # Access token
    access_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_payload = {
        "sub": str(user.user_id),
        "role": user.role,
        "type": "access",
    }
    access_token = _create_token(access_payload, access_expires)
    
    # Refresh token
    refresh_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_payload = {
        "sub": str(user.user_id),
        "type": "refresh",
    }
    refresh_token = _create_token(refresh_payload, refresh_expires)
    
    # Store the refresh token in the DB using the passed-in session
    db_token = models.RefreshToken(
        user_id=user.user_id,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + refresh_expires
    )
    db.add(db_token)
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )

# --- 5. Token Verification and Dependencies ---
def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
) -> models.User:
    """Dependency to get the current authenticated user from an access token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type, expected 'access'",
            )
            
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
        
    user = db.get(models.User, int(user_id))
    if user is None:
        raise credentials_exception
        
    return user

# --- 6. Refresh Token Logic ---
def refresh_access_token(db: Session, refresh_token: str) -> Token:
    """Generates a new set of tokens from a valid refresh token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type, expected 'refresh'",
            )
            
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
    
    db_token = db.scalar(
        select(models.RefreshToken).where(
            models.RefreshToken.token == refresh_token,
            models.RefreshToken.user_id == int(user_id),
            models.RefreshToken.expires_at > datetime.now(timezone.utc)
        )
    )
    
    if not db_token:
        raise credentials_exception
        
    user = db.get(models.User, int(user_id))
    if not user:
        raise credentials_exception
        
    # Revoke the old refresh token
    db.delete(db_token)
    
    # Issue new tokens (and let the calling endpoint commit)
    return create_access_and_refresh_tokens(user, db)

def revoke_refresh_token(db: Session, refresh_token: str):
    """Revokes a refresh token by deleting it from the database."""
    db_token = db.scalar(
        select(models.RefreshToken).where(models.RefreshToken.token == refresh_token)
    )
    if db_token:
        db.delete(db_token)
        db.commit() # This commit is fine, it's a standalone action
    return