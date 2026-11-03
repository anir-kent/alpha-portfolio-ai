from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import audit
from app.market_data import MarketData
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

    def check(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if permission not in PERMISSIONS[user.role]:
            audit.record(
                db, "access_denied", audit.Actor.user(user.username, user.role),
                {"permission": permission, "method": request.method, "path": request.url.path},
            )
            raise HTTPException(403, f"Role '{user.role}' lacks permission '{permission}'")
        return user

    return check


def get_market(request: Request) -> MarketData:
    """The committed market-data snapshot, loaded once per process."""
    state = request.app.state
    if getattr(state, "market", None) is None:
        s = state.settings
        try:
            state.market = MarketData.load(s.market_data_snapshot_path, s.fund_lookthrough_path)
        except FileNotFoundError as e:
            raise HTTPException(503, str(e))
    return state.market
