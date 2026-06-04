from simplified_chatbot import (
    AioSQLiteSessionMemoryStore,
    AioSQLiteSessionStore,
    ChatbotConfig,
    LocalAgentRuntime,
    MCPServerConfig,
    SessionWorkspaceManager,
    SimplifiedChatbot,
)


def test_public_package_imports_are_exposed():
    assert SimplifiedChatbot.__name__ == "SimplifiedChatbot"
    assert ChatbotConfig.__name__ == "ChatbotConfig"
    assert LocalAgentRuntime.__name__ == "LocalAgentRuntime"
    assert MCPServerConfig.__name__ == "MCPServerConfig"
    assert AioSQLiteSessionStore.__name__ == "AioSQLiteSessionStore"
    assert AioSQLiteSessionMemoryStore.__name__ == "AioSQLiteSessionMemoryStore"
    assert SessionWorkspaceManager.__name__ == "SessionWorkspaceManager"
