"""Исходники конфигурации и промптов для агентов.

Содержит dataclass конфигурации и текстовые шаблоны для LLM-промптов.
"""

from agent_system.source.config import config
from agent_system.source.prompts import (
    CONTROLLER_SYSTEM_PROMPT,
    CONTROLLER_USER_PROMPT,
    FINDER_SYSTEM_PROMPT,
    FINDER_USER_PROMPT,
    HINTS_GENERATOR_SYSTEM_PROMPT,
    HINTS_GENERATOR_USER_PROMPT,
    RERANKER_SYSTEM_PROMPT,
    RERANKER_USER_PROMPT,
    VALIDATOR_SYSTEM_PROMPT,
    VALIDATOR_USER_PROMPT,
)

__all__ = [
    "config",
    "FINDER_SYSTEM_PROMPT",
    "FINDER_USER_PROMPT",
    "RERANKER_SYSTEM_PROMPT",
    "RERANKER_USER_PROMPT",
    "CONTROLLER_SYSTEM_PROMPT",
    "CONTROLLER_USER_PROMPT",
    "HINTS_GENERATOR_SYSTEM_PROMPT",
    "HINTS_GENERATOR_USER_PROMPT",
    "VALIDATOR_SYSTEM_PROMPT",
    "VALIDATOR_USER_PROMPT",
]
