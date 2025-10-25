"""Пакет модульной системы агентов поддержки.

Содержит базовые компоненты и агентов:
- Finder — подготовка и переформулирование запросов для RAG и Memory
- RAG — поиск в базе знаний с гибридным подходом (dense + sparse)
- Memory — долгосрочная память пользователей
- ReRanker — валидация и ранжирование результатов
- Controller — оценка качества документов и решение о переформулировании
- HintsGenerator — генерация подсказок для операторов поддержки
- Validator — проверка качества подсказок и решение о регенерации
"""

from agent_system.agents import (
    BaseLLMAgent,
    ControllerAgent,
    FinderAgent,
    HintsGeneratorAgent,
    ReRankerAgent,
    ValidatorAgent,
)
from agent_system.state import AgentState
from agent_system.system import SupportAgentSystem

__all__ = [
    "SupportAgentSystem",
    "BaseLLMAgent",
    "FinderAgent",
    "ReRankerAgent",
    "ControllerAgent",
    "HintsGeneratorAgent",
    "ValidatorAgent",
    "AgentState",
]
