from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionRow, User
from app.rbac import PERMISSIONS
from app.security import token_digest

COOKIE = "session"


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not authenticated")
    row = db.get(SessionRow, token_digest(token))
    if row is None:
        raise HTTPException(401, "Not authenticated")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(401, "Session expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


def require(permission: str):
    """Dependency factory: the server rejects roles lacking `permission`."""

    def check(user: User = Depends(current_user)) -> User:
        if permission not in PERMISSIONS[user.role]:
            # Ticket 02 (audit chain) records this as an "access denied" event.
            raise HTTPException(403, f"Role '{user.role}' lacks permission '{permission}'")
        return user

    return check
