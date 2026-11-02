from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionRow, User
from app.rbac import PERMISSIONS
from app.security import token_digest
from app.timeutil import as_utc

COOKIE = "session"


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def find_session(db: Session, request: Request) -> SessionRow | None:
    """The live (unexpired) session for this request, if any. Expired rows are purged."""
    token = session_token(request)
    row = db.get(SessionRow, token_digest(token)) if token else None
    if row is None:
        return None
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return row


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    row = find_session(db, request)
    user = db.get(User, row.user_id) if row else None
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
