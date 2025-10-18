from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from .. import models, schemas, database, auth

router = APIRouter(prefix="/users", tags=["users"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post(
    "/register",
    response_model=schemas.UserRead,
    summary="Register a new user",
    description="Create an account. `role` must be **candidate** or **company**.",
    responses={400: {"description": "Email already registered"}},
)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.email == user.email).first()
    if exists:
        raise HTTPException(400, "Email already registered")
    hashed = auth.hash_password(user.password)
    db_user = models.User(email=user.email, password_hash=hashed, role=user.role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.post(
    "/login",
    summary="Login and get access + refresh tokens",
    description=(
        "Submit `username` (email) and `password` as form fields. "
        "The response contains a short-lived **access token** and a long-lived **refresh token**. "
        "Use the access token in `Authorization: Bearer <token>` for authenticated requests."
    ),
)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form_data.username
    password = form_data.password

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, refresh_token = auth.issue_token_pair(db, user.user_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"user_id": user.user_id, "role": user.role},
    }

@router.post(
    "/refresh",
    summary="Rotate refresh token and issue a new access token",
    description=(
        "Send your current `refresh_token` (JWT). "
        "If valid and not revoked/expired, this returns a **new access token** and a **new refresh token**. "
        "The old refresh token is revoked."
    ),
)
def refresh(body: schemas.RefreshRequest, db: Session = Depends(get_db)):
    rec = auth.verify_refresh_token(db, body.refresh_token)
    # rotate refresh token and issue a new access
    new_refresh = auth.rotate_refresh_token(db, rec)
    new_access = auth.create_access_token({"sub": rec.user_id})
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "user": {"user_id": rec.user_id},
    }

@router.post(
    "/logout",
    summary="Logout (revoke a refresh token)",
    description="Provide the `refresh_token` to revoke it. Access tokens simply expire.",
)
def logout(body: schemas.LogoutRequest, db: Session = Depends(get_db)):
    auth.revoke_refresh_token(db, body.refresh_token)
    return {"detail": "logged out"}
