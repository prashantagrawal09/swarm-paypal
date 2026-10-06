"""Agent base class: identity, mandate, prompt, allowed tools and the validation gate.

Every agent has:
- an id (`shop:cafe-mei`, `supplier:freshdairy`, `coordinator:swarm`, `claims:swarm`),
- an owner (the person or business it acts for),
- a mandate: hard rules loaded from the database (spending limit, floors, stock...),
- a system prompt file and a fixed set of tools.

Before any tool runs, `require()` runs `validate()` in code. The language model can suggest
an action, but an action outside the tool list or the mandate is refused (and audited),
whatever the model or another agent said.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bus import MessageBus
from app.agents.prompting import load_prompt
from app.clock import Clock
from app.db.models import AgentMessage, AuditLog
from app.llm.client import LLM, Content, Effort, LLMError

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class Action:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str = ""
    reason: str = ""

    @classmethod
    def allow(cls) -> Verdict:
        return cls(True)

    @classmethod
    def deny(cls, code: str, reason: str) -> Verdict:
        return cls(False, code, reason)


class MandateViolation(Exception):
    def __init__(self, agent_id: str, action: Action, verdict: Verdict) -> None:
        super().__init__(f"{agent_id} may not {action.tool}: {verdict.reason}")
        self.agent_id = agent_id
        self.action = action
        self.verdict = verdict


class Agent:
    kind: ClassVar[str]
    prompt_name: ClassVar[str]
    tools: ClassVar[frozenset[str]]

    def __init__(
        self,
        *,
        code: str,
        display_name: str,
        owner: str,
        mandate: dict[str, Any],
        llm: LLM,
        bus: MessageBus,
        clock: Clock,
    ) -> None:
        self.code = code
        self.display_name = display_name
        self.owner = owner
        self.mandate = mandate
        self.llm = llm
        self.bus = bus
        self.clock = clock

    @property
    def agent_id(self) -> str:
        return f"{self.kind}:{self.code}"

    # -- prompt -------------------------------------------------------------------------

    def prompt_values(self) -> dict[str, Any]:
        return {}

    def system_prompt(self) -> str:
        return load_prompt(self.prompt_name).render(**self.prompt_values())

    async def ask(
        self,
        *,
        task: str,
        content: Content,
        schema: type[M],
        fallback: Callable[[], M],
        effort: Effort = "low",
    ) -> tuple[M, str]:
        """Ask the model; on any failure use the deterministic fallback.

        Returns the answer and where it came from ("llm" or "fallback").
        """
        try:
            answer = await self.llm.structured(
                prompt=f"{self.prompt_name}.{task}",
                system=self.system_prompt(),
                content=content,
                schema=schema,
                effort=effort,
            )
            return answer, "llm"
        except LLMError as exc:
            logger.debug("%s %s falling back: %s", self.agent_id, task, exc)
            return fallback(), "fallback"

    # -- the validation gate ------------------------------------------------------------

    def check(self, action: Action) -> Verdict:
        """Agent-specific mandate checks. Override in subclasses."""
        return Verdict.allow()

    def validate(self, action: Action) -> Verdict:
        if action.tool not in self.tools:
            return Verdict.deny("TOOL_NOT_ALLOWED", f"{action.tool} is not one of my tools")
        return self.check(action)

    async def require(self, session: AsyncSession, action: Action) -> None:
        """Run the gate; refuse (and audit) anything outside the mandate."""
        verdict = self.validate(action)
        if verdict.ok:
            return
        session.add(
            AuditLog(
                actor=self.agent_id,
                action=f"refused:{action.tool}",
                details={
                    "code": verdict.code,
                    "reason": verdict.reason,
                    "args": _safe(action.args),
                },
                created_at=self.clock.now(),
            )
        )
        await session.commit()
        raise MandateViolation(self.agent_id, action, verdict)

    # -- messaging ----------------------------------------------------------------------

    async def say(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        to: str,
        type: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        return await self.bus.publish(
            session,
            conversation_id=conversation_id,
            from_agent=self.agent_id,
            to_agent=to,
            type=type,
            text=text,
            payload=payload,
        )


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_safe(v) for v in value]
    if isinstance(value, int | float | str | bool) or value is None:
        return value
    return str(value)
