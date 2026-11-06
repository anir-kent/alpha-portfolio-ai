from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionRow, User
from app.deps import COOKIE, current_user, find_session, get_db
from app.rbac import PERMISSIONS
from app.security import new_token, token_digest, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class Me(BaseModel):
    username: str
    role: str
    permissions: list[str]


def _me(user: User) -> Me:
    return Me(username=user.username, role=user.role, permissions=sorted(PERMISSIONS[user.role]))


@router.post("/login", response_model=Me, operation_id="login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = new_token()
    ttl = timedelta(hours=settings.session_ttl_hours)
    db.add(SessionRow(token_hash=token_digest(token), user_id=user.id, expires_at=datetime.now(UTC) + ttl))
    db.commit()
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
        max_age=int(ttl.total_seconds()), path="/",
    )
    return _me(user)


@router.post("/logout", status_code=204, operation_id="logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    if row := find_session(db, request):
        db.delete(row)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=Me, operation_id="me")
def me(user: User = Depends(current_user)):
    return _me(user)
