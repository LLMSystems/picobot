import asyncio

from simplified_chatbot.tools.tavily import TavilySearchTool


def test_tavily_search_returns_normalized_response(monkeypatch):
    tool = TavilySearchTool(api_key="tvly-test")

    async def fake_post(payload, api_key):
        assert payload["query"] == "latest OpenAI API updates"
        assert payload["topic"] == "general"
        assert payload["search_depth"] == "basic"
        assert payload["max_results"] == 5
        assert payload["include_usage"] is True
        assert api_key == "tvly-test"
        return {
            "query": "latest OpenAI API updates",
            "answer": "OpenAI recently updated its API platform.",
            "results": [
                {
                    "title": "OpenAI API Docs",
                    "url": "https://platform.openai.com/docs",
                    "content": "Official API documentation.",
                    "score": 0.98,
                },
            ],
            "usage": {"credits": 1},
            "response_time": 1.23,
            "request_id": "req_123",
        }

    monkeypatch.setattr(tool, "_post_search", fake_post)

    result = asyncio.run(tool.execute(query="latest OpenAI API updates"))

    assert result == {
        "query": "latest OpenAI API updates",
        "answer": "OpenAI recently updated its API platform.",
        "results": [
            {
                "title": "OpenAI API Docs",
                "url": "https://platform.openai.com/docs",
                "content": "Official API documentation.",
                "score": 0.98,
            },
        ],
        "usage": {"credits": 1},
        "response_time": 1.23,
        "request_id": "req_123",
    }


def test_tavily_search_requires_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    tool = TavilySearchTool(api_key=None)

    result = asyncio.run(tool.execute(query="OpenAI"))

    assert result == "Error: TAVILY_API_KEY is not set"
