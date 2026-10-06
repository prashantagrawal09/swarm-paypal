"""The one place the backend talks to a language model.

Every call goes through `LLM.structured()` (a validated Pydantic object back, using the API's
structured outputs) or `LLM.text()`. The wrapper sets timeouts and retries, refuses to
return anything it could not validate, and logs the prompt name, latency and token usage
of every call.

Callers must treat every failure the same way: fall back to their deterministic behaviour.
That is why there are three implementations:
- `AnthropicLLM`: the real model (used when ANTHROPIC_API_KEY is set),
- `OfflineLLM`: always raises `LLMUnavailable`, so agents run on their deterministic
  policies and templates (no key needed for the demo or CI),
- `ScriptedLLM`: canned answers per prompt name, for tests.

Models never decide money. Structured outputs from the model are choices among options the
code generated, or text; amounts are always computed and validated by code.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar, cast

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
Effort = Literal["low", "medium", "high"]
Content = str | list[dict[str, Any]]


class LLMError(Exception):
    """Any reason the model could not give a usable answer. Callers fall back."""


class LLMUnavailable(LLMError):
    pass


class LLMRefused(LLMError):
    def __init__(self, category: str | None) -> None:
        super().__init__(f"Model declined (category: {category})")
        self.category = category


class LLMFailed(LLMError):
    pass


@dataclass(frozen=True)
class LLMCallRecord:
    prompt: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    status: str = "ok"
    error: str = ""


@dataclass
class LLMStats:
    """Recent calls, for the demo panel and for tests."""

    recent: deque[LLMCallRecord] = field(default_factory=lambda: deque(maxlen=200))

    def record(self, entry: LLMCallRecord) -> None:
        self.recent.append(entry)
        logger.info(
            "llm prompt=%s provider=%s model=%s status=%s latency=%dms in=%d out=%d "
            "cache_read=%d %s",
            entry.prompt,
            entry.provider,
            entry.model,
            entry.status,
            entry.latency_ms,
            entry.input_tokens,
            entry.output_tokens,
            entry.cache_read_tokens,
            entry.error,
        )

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.recent)


class LLM(Protocol):
    provider: str
    stats: LLMStats

    async def structured(
        self,
        *,
        prompt: str,
        system: str,
        content: Content,
        schema: type[M],
        effort: Effort = "low",
        max_tokens: int = 4000,
    ) -> M: ...

    async def text(
        self,
        *,
        prompt: str,
        system: str,
        content: Content,
        effort: Effort = "low",
        max_tokens: int = 2000,
    ) -> str: ...


# ---------------------------------------------------------------------------------------
# The real model
# ---------------------------------------------------------------------------------------


class AnthropicLLM:
    provider = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self.stats = LLMStats()
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    async def structured(
        self,
        *,
        prompt: str,
        system: str,
        content: Content,
        schema: type[M],
        effort: Effort = "low",
        max_tokens: int = 4000,
    ) -> M:
        started = time.monotonic()
        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=_user_turn(content),
                output_format=schema,
                output_config={"effort": effort},
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            self._fail(prompt, started, exc)
        self._check_stop(prompt, started, response)
        parsed = response.parsed_output
        if parsed is None:
            self._record(prompt, started, response, status="invalid", error="no parsed output")
            raise LLMFailed("The model returned no valid structured output")
        self._record(prompt, started, response)
        return parsed

    async def text(
        self,
        *,
        prompt: str,
        system: str,
        content: Content,
        effort: Effort = "low",
        max_tokens: int = 2000,
    ) -> str:
        started = time.monotonic()
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=_user_turn(content),
                output_config={"effort": effort},
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            self._fail(prompt, started, exc)
        self._check_stop(prompt, started, response)
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            self._record(prompt, started, response, status="empty")
            raise LLMFailed("The model returned no text")
        self._record(prompt, started, response)
        return text

    # -- helpers ------------------------------------------------------------------------

    def _check_stop(self, prompt: str, started: float, response: Any) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            self._record(prompt, started, response, status="refused", error=str(category))
            raise LLMRefused(category)
        if response.stop_reason == "max_tokens":
            self._record(prompt, started, response, status="truncated")
            raise LLMFailed("The model ran out of tokens")

    def _fail(self, prompt: str, started: float, exc: Exception) -> Any:
        if isinstance(exc, anthropic.APIStatusError):
            detail = f"http {exc.status_code}"
            if isinstance(exc, anthropic.RateLimitError):
                detail = "rate limited"
            elif isinstance(exc, anthropic.AuthenticationError):
                detail = "authentication failed (check ANTHROPIC_API_KEY)"
        else:
            detail = "network error"
        self.stats.record(
            LLMCallRecord(
                prompt=prompt,
                provider=self.provider,
                model=self.model,
                latency_ms=_ms(started),
                status="error",
                error=detail,
            )
        )
        raise LLMFailed(detail) from exc

    def _record(
        self, prompt: str, started: float, response: Any, *, status: str = "ok", error: str = ""
    ) -> None:
        usage = response.usage
        self.stats.record(
            LLMCallRecord(
                prompt=prompt,
                provider=self.provider,
                model=getattr(response, "model", self.model),
                latency_ms=_ms(started),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                status=status,
                error=error,
            )
        )


# ---------------------------------------------------------------------------------------
# Offline and scripted
# ---------------------------------------------------------------------------------------


class OfflineLLM:
    """No model configured: every call says so and callers use their deterministic path."""

    provider = "offline"

    def __init__(self) -> None:
        self.stats = LLMStats()

    async def structured(self, *, prompt: str, **_: Any) -> Any:
        raise LLMUnavailable("No language model configured (set ANTHROPIC_API_KEY)")

    async def text(self, *, prompt: str, **_: Any) -> str:
        raise LLMUnavailable("No language model configured (set ANTHROPIC_API_KEY)")


Answer = Any | Callable[[Content], Any]


class ScriptedLLM:
    """Test double: answers per prompt name (a value, a callable, or an exception)."""

    provider = "scripted"

    def __init__(self, answers: dict[str, Answer] | None = None) -> None:
        self.answers = dict(answers or {})
        self.calls: list[tuple[str, Content]] = []
        self.stats = LLMStats()

    def _answer(self, prompt: str, content: Content) -> Any:
        self.calls.append((prompt, content))
        if prompt not in self.answers:
            raise LLMUnavailable(f"No scripted answer for {prompt}")
        answer = self.answers[prompt]
        value = answer(content) if callable(answer) and not isinstance(answer, type) else answer
        if isinstance(value, Exception):
            raise value
        return value

    async def structured(
        self, *, prompt: str, system: str, content: Content, schema: type[M], **_: Any
    ) -> M:
        value = self._answer(prompt, content)
        result = value if isinstance(value, schema) else schema.model_validate(value)
        self.stats.record(LLMCallRecord(prompt, self.provider, "scripted", 0))
        return result

    async def text(self, *, prompt: str, system: str, content: Content, **_: Any) -> str:
        value = self._answer(prompt, content)
        self.stats.record(LLMCallRecord(prompt, self.provider, "scripted", 0))
        return str(value)


def build_llm(settings: Settings | None = None) -> LLM:
    settings = settings or get_settings()
    if settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value():
        return AnthropicLLM(settings.anthropic_api_key.get_secret_value(), settings.anthropic_model)
    return OfflineLLM()


def _user_turn(content: Content) -> list[MessageParam]:
    return cast("list[MessageParam]", [{"role": "user", "content": content}])


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
