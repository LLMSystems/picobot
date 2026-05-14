"""Provider factory for simplified_chatbot."""

from __future__ import annotations

import os

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ChatProvider
from simplified_chatbot.providers.openai_compat import OpenAICompatProvider


def build_provider(config: ChatbotConfig) -> ChatProvider:
    """Create the provider implied by the config."""
    if config.provider == "openai_compat":
        return OpenAICompatProvider(
            api_key=config.api_key or os.environ.get("OPENAI_API_KEY"),
            api_base=(
                config.api_base
                or os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("OPENAI_API_BASE")
            ),
        )
    raise ValueError(f"Unsupported provider: {config.provider}")
