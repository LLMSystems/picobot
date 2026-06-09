"""Authentication endpoints: register, login, logout, and current user.

Login state lives entirely in the signed session cookie managed by Starlette's
`SessionMiddleware`; we only ever put ``user_id`` in it (see deps.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from simplified_chatbot.auth.passwords import WeakPasswordError
from simplified_chatbot.auth.users_store import UsernameTakenError, User
from simplified_chatbot.server.common import error_response
from simplified_chatbot.server.deps import (
    SESSION_USER_KEY,
    get_users_store,
    is_admin_user,
    require_user,
)
from simplified_chatbot.server.schemas import (
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, is_admin=is_admin_user(user))


@router.post("/register", response_model=UserResponse)
async def register(request: Request, payload: RegisterRequest) -> UserResponse:
    """Create a new account and log the user in (sets the session cookie)."""
    store = get_users_store(request)
    try:
        user = await store.create_user(payload.username, payload.password)
    except UsernameTakenError:
        # Generic-ish: a taken username is observable by design (we must tell
        # the user to pick another), but we never reveal password validity.
        return error_response(
            request,
            status_code=409,
            code="USERNAME_TAKEN",
            message="That username is already taken",
        )
    except WeakPasswordError as exc:
        return error_response(
            request,
            status_code=422,
            code="WEAK_PASSWORD",
            message=str(exc),
        )
    request.session[SESSION_USER_KEY] = user.id
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
async def login(request: Request, payload: LoginRequest) -> UserResponse:
    """Authenticate and set the session cookie."""
    store = get_users_store(request)
    user = await store.authenticate(payload.username, payload.password)
    if user is None:
        # Identical response for unknown user vs wrong password (no enumeration).
        return error_response(
            request,
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid username or password",
        )
    request.session[SESSION_USER_KEY] = user.id
    return _user_response(user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request) -> LogoutResponse:
    """Clear the session cookie. Idempotent — safe to call when logged out."""
    session = getattr(request, "session", None)
    if session is not None:
        session.clear()
    return LogoutResponse(ok=True)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_user)) -> UserResponse:
    """Return the currently authenticated user, or 401."""
    return _user_response(user)
