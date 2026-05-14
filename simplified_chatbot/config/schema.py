"""Pydantic schema for the first simplified chatbot config."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ChatbotConfig(BaseModel):
    """Minimal configuration needed by the first chatbot version."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    provider: Literal["openai_compat"] = "openai_compat"
    model: str = Field(min_length=1)
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_key", "apiKey"),
    )
    api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_base", "apiBase"),
    )
    max_tokens: int = Field(
        default=1024,
        gt=0,
        validation_alias=AliasChoices("max_tokens", "maxTokens"),
    )
    context_window_tokens: int = Field(
        default=32000,
        gt=0,
        validation_alias=AliasChoices("context_window_tokens", "contextWindowTokens"),
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    system_prompt: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_prompt", "systemPrompt"),
    )
    system_prompt_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_prompt_file", "systemPromptFile"),
    )
    request_timeout: float = Field(
        default=120.0,
        gt=0,
        validation_alias=AliasChoices("request_timeout", "requestTimeout"),
    )
    max_iterations: int = Field(
        default=6,
        gt=0,
        validation_alias=AliasChoices("max_iterations", "maxIterations"),
    )
    enabled_skills: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("enabled_skills", "enabledSkills"),
    )
    disabled_skills: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("disabled_skills", "disabledSkills"),
    )
    skills_dir: str | None = Field(
        default=None,
        validation_alias=AliasChoices("skills_dir", "skillsDir"),
    )
    workspace_root_dir: str | None = Field(
        default=None,
        validation_alias=AliasChoices("workspace_root_dir", "workspaceRootDir"),
    )
    max_upload_file_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        validation_alias=AliasChoices(
            "max_upload_file_bytes",
            "maxUploadFileBytes",
        ),
    )
    max_upload_files_per_request: int = Field(
        default=20,
        gt=0,
        validation_alias=AliasChoices(
            "max_upload_files_per_request",
            "maxUploadFilesPerRequest",
        ),
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "cors_allowed_origins",
            "corsAllowedOrigins",
            "cors_origins",
            "corsOrigins",
        ),
    )

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must not be empty")
        return stripped
