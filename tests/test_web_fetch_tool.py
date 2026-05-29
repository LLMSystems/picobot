import asyncio

from simplified_chatbot.tools.web_fetch import WebFetchTool


def _fake_fetch(status: int, content_type: str, body: str):
    async def fake(url: str, timeout: int):
        return status, content_type, body

    return fake


def test_web_fetch_text_mode_strips_html(monkeypatch):
    tool = WebFetchTool()
    html = (
        "<html><head><style>p{color:red}</style>"
        "<script>alert(1)</script></head>"
        "<body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
    )
    monkeypatch.setattr(
        tool, "_fetch_sync",
        lambda url, timeout: (200, "text/html; charset=utf-8", html),
    )

    result = asyncio.run(tool.execute(url="https://example.com"))

    assert isinstance(result, dict)
    assert result["status"] == 200
    assert result["format"] == "text"
    assert result["truncated"] is False
    assert "Title" in result["content"]
    assert "Hello" in result["content"]
    assert "world" in result["content"]
    assert "<script>" not in result["content"]
    assert "alert(1)" not in result["content"]
    assert "color:red" not in result["content"]


def test_web_fetch_raw_mode_preserves_body(monkeypatch):
    tool = WebFetchTool()
    html = "<html><body><p>Hi</p></body></html>"
    monkeypatch.setattr(
        tool, "_fetch_sync",
        lambda url, timeout: (200, "text/html", html),
    )

    result = asyncio.run(tool.execute(url="https://example.com", format="raw"))

    assert result["content"] == html
    assert result["format"] == "raw"


def test_web_fetch_non_html_returned_as_is(monkeypatch):
    tool = WebFetchTool()
    payload = '{"hello": "world"}'
    monkeypatch.setattr(
        tool, "_fetch_sync",
        lambda url, timeout: (200, "application/json", payload),
    )

    result = asyncio.run(tool.execute(url="https://api.example.com/x"))

    assert result["content"] == payload
    assert result["content_type"] == "application/json"


def test_web_fetch_truncates_long_body(monkeypatch):
    tool = WebFetchTool()
    body = "x" * 5000
    monkeypatch.setattr(
        tool, "_fetch_sync",
        lambda url, timeout: (200, "text/plain", body),
    )

    result = asyncio.run(
        tool.execute(url="https://example.com/big", max_chars=1000),
    )

    assert result["truncated"] is True
    assert result["content"].startswith("x" * 1000)
    assert "[truncated]" in result["content"]


def test_web_fetch_rejects_file_scheme():
    tool = WebFetchTool()

    result = asyncio.run(tool.execute(url="file:///etc/passwd"))

    assert isinstance(result, str)
    assert "only http and https" in result


def test_web_fetch_rejects_empty_url():
    tool = WebFetchTool()

    result = asyncio.run(tool.execute(url=""))

    assert result == "Error: url must not be empty"


def test_web_fetch_rejects_url_without_host():
    tool = WebFetchTool()

    result = asyncio.run(tool.execute(url="https://"))

    assert isinstance(result, str)
    assert "missing a host" in result


def test_web_fetch_rejects_invalid_format():
    tool = WebFetchTool()

    result = asyncio.run(
        tool.execute(url="https://example.com", format="markdown"),
    )

    assert result == "Error: format must be 'text' or 'raw'"


def test_web_fetch_wraps_fetch_errors(monkeypatch):
    tool = WebFetchTool()

    def boom(url: str, timeout: int):
        raise RuntimeError("HTTP 503 from https://example.com: service down")

    monkeypatch.setattr(tool, "_fetch_sync", boom)

    result = asyncio.run(tool.execute(url="https://example.com"))

    assert isinstance(result, str)
    assert result.startswith("Error: web_fetch failed:")
    assert "503" in result


def test_web_fetch_detects_html_without_content_type(monkeypatch):
    tool = WebFetchTool()
    body = "<!doctype html><html><body><p>Detected</p></body></html>"
    monkeypatch.setattr(
        tool, "_fetch_sync",
        lambda url, timeout: (200, "application/octet-stream", body),
    )

    result = asyncio.run(tool.execute(url="https://example.com"))

    assert "Detected" in result["content"]
    assert "<p>" not in result["content"]
