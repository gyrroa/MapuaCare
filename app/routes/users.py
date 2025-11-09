from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from .. import models, schemas, database, auth
# --- MODIFIED ---
from ..database import get_db # Import the central get_db
# ----------------

router = APIRouter(prefix="/users", tags=["users"])

# --- REMOVED ---
# The local get_db() function is no longer needed
# ---------------

# --- MODIFIED: Import hashing functions from auth ---
from ..auth import verify_password, get_password_hash
# ----------------

# ---------------------------
# CREATE USER
# ---------------------------
@router.post(
    "/register",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a user. Role must be 'candidate' or 'company'.",
)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db), # <-- Uses central get_db
):
    if user.role not in ("candidate", "company"):
        raise HTTPException(400, "Role must be 'candidate' or 'company'")
    
    if db.scalar(select(models.User).where(models.User.email == user.email)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        hashed_password=hashed_password,
        role=user.role,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# ---------------------------
# LOGIN
# ---------------------------
@router.post(
    "/login",
    # --- vvv CHANGE 1: Update the response_model vvv ---
    response_model=auth.LoginResponse, 
    # --- ^^^ CHANGE 1: Update the response_model ^^^ ---
    summary="User login",
    description="Get an access token and refresh token.",
)
def login_for_access_token(
    form_data: auth.OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db), # <-- Uses central get_db
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # --- MODIFIED: Pass the db session ---
    tokens = auth.create_access_and_refresh_tokens(user, db)
    
    # --- THIS IS THE FIX ---
    db.commit() # Save the new refresh token to the database
    # -----------------------

    # --- vvv CHANGE 2: Return a dictionary that includes the user vvv ---
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": tokens.token_type,
        "user": user  # <-- This is the missing piece
    }
    # --- ^^^ CHANGE 2: Return a dictionary that includes the user ^^^ ---


# ---------------------------
# GET CURRENT USER
# ---------------------------
@router.get(
    "/me",
    response_model=schemas.UserRead,
    summary="Get current user",
    description="See your own user details.",
)
def read_users_me(
    current_user: models.User = Depends(auth.get_current_user),
):
    return current_user

# ---------------------------
# REFRESH TOKEN
# ---------------------------
@router.post(
    "/refresh",
    response_model=auth.Token,
    summary="Refresh access token",
    description="Get a new access token using a refresh token.",
)
def refresh_token(
    payload: schemas.RefreshRequest,
    db: Session = Depends(get_db), # <-- Uses central get_db
):
    # --- MODIFIED: Pass the db session ---
    new_tokens = auth.refresh_access_token(db, payload.refresh_token)
    db.commit() # Commit the token revocation/creation
    return new_tokens

# ---------------------------
# LOGOUT
# ---------------------------
@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (Revoke Refresh Token)",
    description="Revokes the provided refresh token. Client must delete tokens.",
)
def logout(
    payload: schemas.LogoutRequest,
    db: Session = Depends(get_db), # <-- Uses central get_db
):
    auth.revoke_refresh_token(db, payload.refresh_token)
    return None

# ---------------------------
# UPDATE EMAIL
# ---------------------------
@router.put(
    "/me/email",
    response_model=schemas.UserRead,
    summary="Update your email",
    description="Securely change your login email. This requires your current password.",
    responses={
        400: {"description": "Email already in use"},
        401: {"description": "Invalid password"},
    },
)
def update_my_email(
    data: schemas.EmailUpdate,
    db: Session = Depends(get_db), # <-- Uses central get_db
    current_user: models.User = Depends(auth.get_current_user),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    if data.new_email == current_user.email:
        return current_user 

    existing_user = db.scalar(
        select(models.User).where(models.User.email == data.new_email)
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    current_user.email = data.new_email
    db.commit()
    db.refresh(current_user)
    
    return current_user