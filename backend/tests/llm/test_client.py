"""The LLM wrapper: structured outputs, stop reasons, errors, logging of usage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.llm.client import (
    AnthropicLLM,
    LLMFailed,
    LLMRefused,
    LLMUnavailable,
    OfflineLLM,
    ScriptedLLM,
    build_llm,
)


class Pick(BaseModel):
    label: str
    message: str


def response(**overrides: Any) -> SimpleNamespace:
    base = {
        "stop_reason": "end_turn",
        "stop_details": None,
        "model": "claude-sonnet-5-5",
        "usage": SimpleNamespace(input_tokens=120, output_tokens=30, cache_read_input_tokens=0),
        "parsed_output": Pick(label="beat", message="We can do better."),
        "content": [
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Hello there"),
        ],
    }
    return SimpleNamespace(**{**base, **overrides})


class FakeMessages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    create = parse


def llm_with(result: Any) -> tuple[AnthropicLLM, FakeMessages]:
    messages = FakeMessages(result)
    client = SimpleNamespace(messages=messages)
    return AnthropicLLM("key", "claude-sonnet-5-5", client=client), messages  # type: ignore[arg-type]


async def test_structured_output_uses_parse_with_schema_and_effort():
    llm, messages = llm_with(response())
    pick = await llm.structured(
        prompt="supplier_agent.quote", system="sys", content="task", schema=Pick, effort="low"
    )
    assert pick.label == "beat"
    call = messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_format"] is Pick
    assert call["output_config"] == {"effort": "low"}
    assert call["messages"] == [{"role": "user", "content": "task"}]
    assert "tool_choice" not in call and "temperature" not in call
    record = llm.stats.recent[-1]
    assert (record.prompt, record.input_tokens, record.output_tokens, record.status) == (
        "supplier_agent.quote",
        120,
        30,
        "ok",
    )


async def test_text_joins_text_blocks_only():
    llm, _ = llm_with(response())
    assert await llm.text(prompt="p", system="s", content="c") == "Hello there"


async def test_refusal_and_truncation_raise():
    llm, _ = llm_with(
        response(stop_reason="refusal", stop_details=SimpleNamespace(category="general_harms"))
    )
    with pytest.raises(LLMRefused) as exc:
        await llm.structured(prompt="p", system="s", content="c", schema=Pick)
    assert exc.value.category == "general_harms"
    llm, _ = llm_with(response(stop_reason="max_tokens"))
    with pytest.raises(LLMFailed):
        await llm.structured(prompt="p", system="s", content="c", schema=Pick)
    llm, _ = llm_with(response(parsed_output=None))
    with pytest.raises(LLMFailed):
        await llm.structured(prompt="p", system="s", content="c", schema=Pick)


async def test_api_errors_become_llm_failed():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        anthropic.RateLimitError(
            message="slow", response=httpx2.Response(429, request=request), body=None
        ),
        anthropic.APIConnectionError(request=request),
    ]
    for error in errors:
        llm, _ = llm_with(error)
        with pytest.raises(LLMFailed):
            await llm.structured(prompt="p", system="s", content="c", schema=Pick)
        assert llm.stats.recent[-1].status == "error"


async def test_offline_and_scripted():
    with pytest.raises(LLMUnavailable):
        await OfflineLLM().structured(prompt="p", system="s", content="c", schema=Pick)
    scripted = ScriptedLLM(
        {
            "a": {"label": "x", "message": "m"},
            "b": ValueError("boom"),
            "c": lambda content: {"label": content, "message": ""},
        }
    )
    assert (await scripted.structured(prompt="a", system="", content="", schema=Pick)).label == "x"
    assert (
        await scripted.structured(prompt="c", system="", content="hi", schema=Pick)
    ).label == "hi"
    with pytest.raises(ValueError):
        await scripted.structured(prompt="b", system="", content="", schema=Pick)
    with pytest.raises(LLMUnavailable):
        await scripted.structured(prompt="missing", system="", content="", schema=Pick)


def test_build_llm_picks_offline_without_a_key():
    assert isinstance(build_llm(Settings(anthropic_api_key=None)), OfflineLLM)
    real = build_llm(
        Settings(anthropic_api_key=SecretStr("sk-test"), anthropic_model="claude-sonnet-5-5")
    )
    assert isinstance(real, AnthropicLLM) and real.model == "claude-sonnet-5-5"
