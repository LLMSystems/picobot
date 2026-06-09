"""FastAPI endpoints for managing the global skill library."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Request

from simplified_chatbot.auth.users_store import User
from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.deps import require_user
from simplified_chatbot.server.schemas import (
    SkillCreateRequest,
    SkillDisableRequest,
    SkillInfo,
    SkillListResponse,
    SkillMutationResponse,
)
from simplified_chatbot.skills.loader import (
    SkillBuiltinReadOnlyError,
    SkillContentInvalidError,
    SkillNameInvalidError,
    SkillNotFoundError,
)

router = APIRouter()


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    request: Request,
    user: User = Depends(require_user),
) -> SkillListResponse:
    """List builtin + shared + this user's custom skills with enabled state."""
    runtime = get_runtime(request)
    try:
        skills = runtime.list_skills(user_id=user.id)
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="SKILLS_NOT_AVAILABLE",
            message=str(exc),
        )
    return SkillListResponse(skills=[SkillInfo.model_validate(item) for item in skills])


@router.post("/skills", response_model=SkillMutationResponse)
async def create_skill(
    request: Request,
    body: SkillCreateRequest,
    user: User = Depends(require_user),
) -> SkillMutationResponse:
    """Create or overwrite a custom skill in the caller's own library."""
    runtime = get_runtime(request)
    files: dict[str, bytes] = {}
    for item in body.files:
        try:
            files[item.path] = base64.b64decode(item.content_base64, validate=True)
        except Exception:
            return error_response(
                request,
                status_code=400,
                code="SKILL_FILE_INVALID",
                message=f"File '{item.path}' is not valid base64",
            )
    try:
        runtime.create_skill(body.name, body.content, files=files or None, user_id=user.id)
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="SKILLS_NOT_AVAILABLE",
            message=str(exc),
        )
    except SkillNameInvalidError as exc:
        return error_response(
            request,
            status_code=400,
            code="SKILL_NAME_INVALID",
            message=str(exc),
        )
    except SkillContentInvalidError as exc:
        return error_response(
            request,
            status_code=400,
            code="SKILL_CONTENT_INVALID",
            message=str(exc),
        )
    return SkillMutationResponse(name=body.name)


@router.delete("/skills/{name}", response_model=SkillMutationResponse)
async def delete_skill(
    request: Request,
    name: str,
    user: User = Depends(require_user),
) -> SkillMutationResponse:
    """Delete one of the caller's custom skills. Builtin/shared are read-only."""
    runtime = get_runtime(request)
    try:
        runtime.delete_skill(name, user_id=user.id)
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="SKILLS_NOT_AVAILABLE",
            message=str(exc),
        )
    except SkillBuiltinReadOnlyError as exc:
        return error_response(
            request,
            status_code=400,
            code="SKILL_BUILTIN_READ_ONLY",
            message=str(exc),
        )
    except SkillNameInvalidError as exc:
        return error_response(
            request,
            status_code=400,
            code="SKILL_NAME_INVALID",
            message=str(exc),
        )
    except SkillNotFoundError:
        return error_response(
            request,
            status_code=404,
            code="SKILL_NOT_FOUND",
            message=f"Skill '{name}' not found",
        )
    return SkillMutationResponse(name=name)


@router.patch("/skills/{name}", response_model=SkillMutationResponse)
async def set_skill_disabled(
    request: Request,
    name: str,
    body: SkillDisableRequest,
    user: User = Depends(require_user),
) -> SkillMutationResponse:
    """Enable or disable a skill for the caller's newly created sessions."""
    runtime = get_runtime(request)
    try:
        runtime.set_skill_disabled(name, body.disabled, user_id=user.id)
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="SKILLS_NOT_AVAILABLE",
            message=str(exc),
        )
    return SkillMutationResponse(name=name)
