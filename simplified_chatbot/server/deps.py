"""Shared auth dependencies for FastAPI endpoints.

The signed session cookie (Starlette `SessionMiddleware`) only stores a
``user_id``. These helpers resolve that id back to a [User][simplified_chatbot.auth.users_store.User]
and gate protected routes.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from simplified_chatbot.auth.users_store import User, UsersStore
from simplified_chatbot.server.common import get_runtime

SESSION_USER_KEY = "user_id"


def _admin_usernames() -> set[str]:
    """Admin accounts, from the ADMIN_USERNAMES env var (comma-separated).

    Read at request time so the set follows the loaded .env. Usernames are
    normalized to lowercase to match how UsersStore stores them.
    """
    raw = os.environ.get("ADMIN_USERNAMES", "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


def is_admin_user(user: User) -> bool:
    """True iff the user's name is listed in ADMIN_USERNAMES."""
    return user.username.lower() in _admin_usernames()


class SessionAccessError(Exception):
    """Raised when a user touches a session they do not own.

    Carries the session_id so the app-level handler can render a 404 that is
    indistinguishable from a genuinely missing session (no existence leak).
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


def get_users_store(conn: HTTPConnection) -> UsersStore:
    """Return the UsersStore stored on FastAPI app state."""
    store = getattr(conn.app.state, "users_store", None)
    if not isinstance(store, UsersStore):
        raise RuntimeError("UsersStore is not initialized")
    return store


async def get_current_user(conn: HTTPConnection) -> User | None:
    """Resolve the logged-in user from the session cookie, or None.

    Typed against HTTPConnection (the shared base of Request and WebSocket) so
    the same gate works on HTTP routes and the screencast WebSocket. Returns
    None (rather than raising) so callers that allow anonymous access can branch
    on it. A stale cookie pointing at a deleted user resolves to None as well.
    """
    session = getattr(conn, "session", None)
    if not session:
        return None
    user_id = session.get(SESSION_USER_KEY)
    if not isinstance(user_id, int):
        return None
    store = get_users_store(conn)
    return await store.get_by_id(user_id)


async def require_user(conn: HTTPConnection) -> User:
    """FastAPI dependency: 401 unless a valid session cookie is present."""
    user = await get_current_user(conn)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(conn: HTTPConnection) -> User:
    """FastAPI dependency: 401 if anonymous, 403 if logged in but not an admin.

    Gates the operational dashboard (metrics/alerts), which exposes system-wide
    and cross-user data that regular users must not see.
    """
    user = await require_user(conn)
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


async def enforce_session_ownership(conn: HTTPConnection) -> None:
    """Router-level dependency for ``/sessions/{session_id}/...`` routes.

    A no-op on collection routes (``GET/POST /sessions``) and on routes that
    carry the session id elsewhere (chat uses a request body). For every route
    with a ``session_id`` path param it 404s unless the logged-in user owns it.
    Owning means ``session.user_id == current_user.id``; legacy NULL-owner
    sessions are owned by nobody and therefore invisible to everyone.
    """
    session_id = conn.path_params.get("session_id")
    if not session_id:
        return
    user = await require_user(conn)
    runtime = get_runtime(conn)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None or summary.get("user_id") != user.id:
        raise SessionAccessError(session_id)


async def claim_or_check_session(request: Request, session_id: str, user: User) -> object | None:
    """Ownership gate for body/query-scoped writes (chat endpoints).

    Returns an error JSONResponse if the session exists but belongs to someone
    else; transparently creates a fresh session owned by ``user`` when it does
    not exist yet (chatting into a new session id is a valid create path).
    Returns None when the caller may proceed.
    """
    from simplified_chatbot.server.common import error_response

    runtime = get_runtime(request)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        # Leave the title NULL so it's derived from the first message, matching
        # the pre-auth implicit-create behaviour.
        await runtime.create_session_async(
            session_id=session_id,
            user_id=user.id,
            apply_default_title=False,
        )
        return None
    if summary.get("user_id") != user.id:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    return None
