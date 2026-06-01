"""Pydantic schema for the first simplified chatbot config."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class ChatbotConfig(BaseModel):
    """Minimal configuration needed by the first chatbot version."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    provider: Literal["openai_compat"] = "openai_compat"
    model: str = Field(min_length=1)
    subagent_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("subagent_model", "subagentModel"),
    )
    available_models: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("available_models", "availableModels"),
    )
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
    memory_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("memory_enabled", "memoryEnabled"),
    )
    memory_compression_ratio: float = Field(
        default=0.5,
        ge=0.1,
        le=0.95,
        validation_alias=AliasChoices("memory_compression_ratio", "memoryCompressionRatio"),
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
    max_concurrent_subagents: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices(
            "max_concurrent_subagents",
            "maxConcurrentSubagents",
        ),
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
        default="custom_skills",
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
    
    # Browser tool config
    """
    "browser": {
        "chromeDebuggingPort": null
    }
    """
    browser: dict | None = Field(
        default=None,
        validation_alias=AliasChoices("browser"),
    )
    
    

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must not be empty")
        return stripped

    @field_validator("subagent_model")
    @classmethod
    def _strip_subagent_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("subagent_model must not be empty when provided")
        return stripped

    @field_validator("available_models")
    @classmethod
    def _normalize_available_models(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, str):
                raise TypeError(f"available_models[{index}] must be a string")
            stripped = item.strip()
            if not stripped:
                raise ValueError(f"available_models[{index}] must not be empty")
            if stripped in seen:
                continue
            seen.add(stripped)
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def _validate_model_membership(self) -> "ChatbotConfig":
        if self.available_models and self.model not in self.available_models:
            raise ValueError("model must be included in available_models when provided")
        if (
            self.subagent_model is not None
            and self.available_models
            and self.subagent_model not in self.available_models
        ):
            raise ValueError(
                "subagent_model must be included in available_models when provided",
            )
        return self
