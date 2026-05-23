from __future__ import annotations

import base64

from simplified_chatbot.providers.openai_compat import (
    _serialize_message,
    _serialize_messages,
)


def test_serialize_messages_keeps_text_content_unchanged():
    payload = _serialize_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    )

    assert payload == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]


def test_serialize_message_converts_image_url_block_to_openai_format():
    payload = _serialize_message(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image", "url": "https://example.com/cat.png", "detail": "high"},
            ],
        },
    )

    assert payload == {
        "role": "user",
        "content": [
            {"type": "text", "text": "What is in this image?"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.com/cat.png",
                    "detail": "high",
                },
            },
        ],
    }


def test_serialize_message_reads_local_image_file_as_data_url(tmp_path):
    image_path = tmp_path / "cat.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    payload = _serialize_message(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this local image"},
                {"type": "image", "path": str(image_path)},
            ],
        },
    )

    image_part = payload["content"][1]
    assert image_part["type"] == "image_url"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    assert image_part["image_url"] == {
        "url": f"data:image/png;base64,{encoded}",
        "detail": "auto",
    }


def test_serialize_message_preserves_tool_fields():
    payload = _serialize_message(
        {
            "role": "assistant",
            "content": "Calling a tool",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                },
            ],
        },
    )

    assert payload["tool_calls"][0]["id"] == "call_1"
