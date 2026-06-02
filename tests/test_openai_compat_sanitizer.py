"""Regression tests for the OpenAI-compatible provider's output sanitizers.

Some models (DeepSeek family) leak full-width-bar control tokens such as
`<｜tool▁calls▁begin｜>` — or the truncated `<｜DSML｜tool_calls` observed in
the wild — into the content/reasoning channel when the upstream server fails to
parse them. They must never reach persistence or the UI.
"""

from simplified_chatbot.providers.openai_compat import _strip_special_tokens


def test_strips_truncated_leaked_tool_call_token():
    assert _strip_special_tokens("\n\n<｜DSML｜tool_calls") == "\n\n"


def test_strips_well_formed_control_tokens_inline():
    assert (
        _strip_special_tokens("hello <｜tool▁calls▁begin｜> world")
        == "hello  world"
    )
    assert _strip_special_tokens("a<｜tool▁sep｜>b") == "ab"


def test_preserves_regular_pipe_and_plain_angle_brackets():
    text = "use a | b and compare x < y or <tag>"
    assert _strip_special_tokens(text) == text


def test_leaves_think_tags_to_the_dedicated_handler():
    # Think-tag handling lives in _strip_think_tags / _split_reasoning_channel;
    # the special-token stripper must not touch them.
    assert _strip_special_tokens("<think>x</think>ok") == "<think>x</think>ok"
