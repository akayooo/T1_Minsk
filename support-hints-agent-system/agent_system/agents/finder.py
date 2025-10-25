"""Агент "Искатель" (Finder) — подготовка запроса для RAG.

Очищает текст, исправляет опечатки и приводит запрос к форме, удобной для Retriever.
"""

import logging
import re
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from agent_system.agents.base_agent import BaseLLMAgent
from agent_system.source.prompts import FINDER_REFORMULATE_PROMPT, FINDER_SYSTEM_PROMPT, FINDER_USER_PROMPT
from agent_system.state import AgentState, FinderResult

logger = logging.getLogger(__name__)


def _basic_normalize(text: str) -> str:
    """Минимальная предобработка: нормализация кавычек, фильтр символов и пробелов."""
    text = text.replace(""", '"').replace(""", '"').replace("'", "'")
    text = re.sub(r"[^\w\s\d\.,!?-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class FinderAgent(BaseLLMAgent):
    """Готовит нормализованный поисковый запрос для RAG."""

    def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None) -> None:
        super().__init__(llm, model_name)
        self.parser = JsonOutputParser()

    def prepare_query(self, user_request: str) -> FinderResult:
        """Возвращает словарь с исходным запросом, retriever_query и memory_query."""
        original = _basic_normalize(user_request)

        user_prompt = FINDER_USER_PROMPT.format(user_request=original)

        try:
            result = self._invoke_llm(
                system_prompt=FINDER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                parser=self.parser,
                agent_name="Finder"
            )
            normalized = _basic_normalize(result.get("normalized_query", original).lower())
            memory_query = _basic_normalize(result.get("memory_query", f"пользователь {original}").lower())
        except Exception as e:
            logger.warning("Не удалось нормализовать через LLM — использую базовую нормализацию",
            extra={"error": str(e)})
            normalized = original.lower()
            memory_query = f"пользователь {original.lower()}"

        finder_result: FinderResult = {
            "normalized_query": normalized,
            "original_query": original,
            "memory_query": memory_query,
        }
        logger.info(
            "Искатель подготовил запросы для RAG и Memory",
            extra={
                "retriever_query": normalized[:150],
                "memory_query": memory_query[:150]
            }
        )
        return finder_result

    def reformulate_query(
        self,
        original_query: str,
        previous_query: str,
        feedback: str,
        query_history: list
    ) -> FinderResult:
        """Переформулирует запрос с учетом обратной связи от контроллера.

        Args:
            original_query: Исходный пользовательский запрос
            previous_query: Предыдущая формулировка запроса
            feedback: Обратная связь от контроллера с рекомендациями
            query_history: История предыдущих попыток запросов

        Returns:
            FinderResult с новым нормализованным запросом
        """
        original = _basic_normalize(original_query)

        history_text = "\n".join([
            f"{i+1}. {attempt.get('query', 'N/A')}"
            for i, attempt in enumerate(query_history)
        ]) if query_history else "Нет предыдущих попыток"

        user_prompt = FINDER_REFORMULATE_PROMPT.format(
            original_query=original,
            previous_query=previous_query,
            query_history=history_text,
            feedback=feedback
        )

        try:
            result = self._invoke_llm(
                system_prompt=FINDER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                parser=self.parser,
                agent_name="Finder (reformulate)"
            )
            normalized = _basic_normalize(result.get("normalized_query", original).lower())
            memory_query = _basic_normalize(result.get("memory_query", f"пользователь {original}").lower())

            logger.info(
                "Искатель переформулировал запросы",
                extra={
                    "previous_retriever": previous_query[:100],
                    "new_retriever": normalized[:100],
                    "new_memory": memory_query[:100]
                }
            )
        except Exception as e:
            logger.warning(
                "Не удалось переформулировать через LLM — добавляю вариацию",
                extra={"error": str(e)}
            )
            normalized = f"{original.lower()} альтернатива"
            memory_query = f"пользователь {original.lower()} история"

        finder_result: FinderResult = {
            "normalized_query": normalized,
            "original_query": original,
            "memory_query": memory_query,
        }

        return finder_result

    def process_state(self, state: AgentState) -> AgentState:
        """Сохраняет результат в metadata графа и помечает шаг завершенным."""
        user_request = state["user_request"]
        finder_result = self.prepare_query(user_request)
        state["metadata"] = {**state.get("metadata", {}), "finder": finder_result}
        state["current_step"] = "finder_complete"
        return state
