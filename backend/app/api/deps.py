"""Shared API dependencies: current user, workspace access control, request limits.

Access rules
- Demo workspace: anyone (signed in or not) can read and ask; nobody can modify it.
- Other workspaces: only members can read/ask; members can modify; only the owner can delete.
- Anything addressed by its own id (source, column, run, ...) is checked through its workspace.
- Missing and forbidden workspaces both return 404, so ids can't be probed.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.limits import cost_tracker, rate_limiter
from app.core.security import SESSION_COOKIE, decode_token
from app.db.models import User, Workspace, WorkspaceMember
from app.db.session import get_db


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        return None
    user_id = decode_token(token)
    return db.get(User, user_id) if user_id else None


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    return user


def member_role(db: Session, workspace_id: str, user: User | None) -> str | None:
    if user is None:
        return None
    m = db.get(WorkspaceMember, (workspace_id, user.id))
    return m.role if m else None


def ensure_access(
    db: Session, workspace_id: str, user: User | None, *, write: bool = False, owner: bool = False
) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    role = member_role(db, ws.id, user)
    if ws.is_demo:
        if write or owner:
            raise HTTPException(status_code=403, detail="the demo workspace is read-only")
        return ws
    if role is None:
        if user is None:
            raise HTTPException(status_code=401, detail="sign in to open this workspace")
        raise HTTPException(status_code=404, detail="workspace not found")
    if owner and role != "owner":
        raise HTTPException(status_code=403, detail="only the workspace owner can do this")
    return ws


def get_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> Workspace:
    return ensure_access(db, workspace_id, user)


def get_writable_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> Workspace:
    return ensure_access(db, workspace_id, user, write=True)


def get_owned_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> Workspace:
    return ensure_access(db, workspace_id, user, owner=True)


# ---------------------------------------------------------------- limits


@dataclass
class Caller:
    user: User | None
    key: str  # "user:<id>" or "ip:<addr>"

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None


def client_ip(request: Request) -> str:
    # Behind a proxy, the platform sets X-Forwarded-For; take the first hop.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_caller(request: Request, user: User | None = Depends(get_current_user)) -> Caller:
    return Caller(user=user, key=f"user:{user.id}" if user else f"ip:{client_ip(request)}")


def enforce_limits(caller: Caller = Depends(get_caller)) -> Caller:
    """Per-minute rate limit and daily LLM cost cap for question/SQL endpoints."""
    retry = rate_limiter().check(caller.key)
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Wait a moment and try again.",
            headers={"Retry-After": str(int(retry) + 1)},
        )
    cap = get_settings().daily_cost_cap_usd
    if cost_tracker().spent(caller.key) >= cap:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily usage limit reached (${cap:.2f} of model usage). It resets at midnight UTC."
            ),
        )
    return caller
