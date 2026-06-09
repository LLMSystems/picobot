"""Shared auth dependencies for FastAPI endpoints.

The signed session cookie (Starlette `SessionMiddleware`) only stores a
``user_id``. These helpers resolve that id back to a [User][simplified_chatbot.auth.users_store.User]
and gate protected routes.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from simplified_chatbot.auth.users_store import User, UsersStore
from simplified_chatbot.server.common import get_runtime

SESSION_USER_KEY = "user_id"


class SessionAccessError(Exception):
    """Raised when a user touches a session they do not own.

    Carries the session_id so the app-level handler can render a 404 that is
    indistinguishable from a genuinely missing session (no existence leak).
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


def get_users_store(request: Request) -> UsersStore:
    """Return the UsersStore stored on FastAPI app state."""
    store = getattr(request.app.state, "users_store", None)
    if not isinstance(store, UsersStore):
        raise RuntimeError("UsersStore is not initialized")
    return store


async def get_current_user(request: Request) -> User | None:
    """Resolve the logged-in user from the session cookie, or None.

    Returns None (rather than raising) so callers that allow anonymous access
    can branch on it. A stale cookie pointing at a deleted user resolves to
    None as well.
    """
    session = getattr(request, "session", None)
    if not session:
        return None
    user_id = session.get(SESSION_USER_KEY)
    if not isinstance(user_id, int):
        return None
    store = get_users_store(request)
    return await store.get_by_id(user_id)


async def require_user(request: Request) -> User:
    """FastAPI dependency: 401 unless a valid session cookie is present."""
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def enforce_session_ownership(request: Request) -> None:
    """Router-level dependency for ``/sessions/{session_id}/...`` routes.

    A no-op on collection routes (``GET/POST /sessions``) and on routes that
    carry the session id elsewhere (chat uses a request body). For every route
    with a ``session_id`` path param it 404s unless the logged-in user owns it.
    Owning means ``session.user_id == current_user.id``; legacy NULL-owner
    sessions are owned by nobody and therefore invisible to everyone.
    """
    session_id = request.path_params.get("session_id")
    if not session_id:
        return
    user = await require_user(request)
    runtime = get_runtime(request)
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
