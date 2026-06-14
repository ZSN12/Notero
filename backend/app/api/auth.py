from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Response
from sqlalchemy.orm import Session
import time
import os
import uuid
from pathlib import Path
from app.core.database import get_db
from app.core.auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_refresh_token, get_current_user
from app.core.login_tracker import get_attempts, record_failure, clear_attempts
from app.api.schemas import UserCreate, UserLogin, UserResponse, Token, TokenRefresh, TokenRefreshResponse, PasswordReset, UserProfileUpdate, PasswordChange
from app.models import User
from app.config import BASE_DIR

router = APIRouter(prefix="/api/auth", tags=["auth"])

AVATAR_DIR = BASE_DIR / "uploads" / "avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        security_question=data.security_question,
        security_answer_hash=hash_password(data.security_answer) if data.security_answer else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def _set_auth_cookie(response: Response, token: str) -> None:
    """Set HttpOnly Secure cookie for JWT access token."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/login", response_model=Token)
def login(data: UserLogin, response: Response, db: Session = Depends(get_db)):
    email = data.email

    # Check if account is locked
    attempts = get_attempts(email)
    if attempts and attempts.get("locked_until") and time.time() < attempts["locked_until"]:
        remaining = int(attempts["locked_until"] - time.time())
        raise HTTPException(
            status_code=429,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining} seconds."
        )

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(data.password, user.password_hash):
        # Record failed attempt
        remaining, locked = record_failure(email)
        if locked:
            raise HTTPException(
                status_code=429,
                detail=f"Account locked due to too many failed attempts. Try again in {remaining} seconds."
            )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Successful login: reset failed attempts
    clear_attempts(email)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _set_auth_cookie(response, access_token)
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh_token(data: TokenRefresh, response: Response, db: Session = Depends(get_db)):
    user_id = decode_refresh_token(data.refresh_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = create_access_token(user.id)
    _set_auth_cookie(response, new_access_token)
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"detail": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(data: PasswordReset, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.security_question or not user.security_answer_hash:
        raise HTTPException(
            status_code=400,
            detail="This account does not have a security question set. Please contact support."
        )

    if not verify_password(data.security_answer, user.security_answer_hash):
        raise HTTPException(status_code=403, detail="Incorrect security answer")

    user.password_hash = hash_password(data.new_password)
    db.commit()
    clear_attempts(data.email)
    return {"status": "ok", "message": "Password has been reset successfully"}


@router.put("/profile", response_model=UserResponse)
def update_profile(data: UserProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.username is not None:
        current_user.username = data.username
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(data: PasswordChange, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "ok", "message": "Password changed successfully"}


@router.post("/avatar", status_code=status.HTTP_200_OK)
async def upload_avatar(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_AVATAR_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large: {len(content)} bytes (max {MAX_AVATAR_SIZE} bytes)")

    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = AVATAR_DIR / filename
    with open(filepath, "wb") as f:
        f.write(content)

    current_user.avatar_url = filename
    db.commit()
    return {"status": "ok", "avatar_url": f"/api/auth/avatar/{current_user.id}"}


@router.get("/avatar/{user_id}")
def get_avatar(user_id: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    filename = os.path.basename(user.avatar_url)
    filepath = (AVATAR_DIR / filename).resolve()
    if not filepath.is_relative_to(AVATAR_DIR.resolve()) or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Avatar file not found")

    return FileResponse(filepath)
