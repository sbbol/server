"""Модели intent-системы."""

from dataclasses import dataclass, field
from enum import Enum


class ResponseMode(str, Enum):
    """Как формируется ответ пользователю."""
    DATA = "data"              # факты из инструментов — без LLM
    NAVIGATE = "navigate"      # кнопка перехода — без LLM
    PERMISSION = "permission"  # отказ в правах — без LLM
    FAQ = "faq"                # база знаний + LLM


@dataclass
class MatchedIntent:
    intent_id: str
    response_mode: ResponseMode
    tool: str | None = None
    tool_args: dict = field(default_factory=dict)
    score: float = 0.0
    guided: bool = False


@dataclass
class OrchestratorResult:
    text: str
    actions: list[dict] = field(default_factory=list)
    use_llm: bool = False
    llm_context: str = ""
