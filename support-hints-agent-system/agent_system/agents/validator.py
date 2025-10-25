"""Агент проверки качества подсказок для операторов.

Анализирует сгенерированные подсказки и решает, достаточно ли они
конкретны и релевантны для решения проблемы пользователя.
"""

import logging
from typing import List, Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from agent_system.agents.base_agent import BaseLLMAgent
from agent_system.source.prompts import VALIDATOR_SYSTEM_PROMPT, VALIDATOR_USER_PROMPT
from agent_system.state import AgentState, ValidatorResult

logger = logging.getLogger(__name__)


class ValidatorAgent(BaseLLMAgent):
    """Проверяет качество подсказок для оператора."""

    def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None, max_attempts: int = 2) -> None:
        super().__init__(llm, model_name)
        self.parser = JsonOutputParser()
        self.max_attempts = max_attempts

    def validate_hints(
        self,
        user_request: str,
        suggested_actions: List[str],
        attempt: int,
        previous_feedback: List[str]
    ) -> ValidatorResult:
        """Оценивает качество подсказок для оператора.

        Args:
            user_request: Исходный запрос пользователя (краткий контекст)
            suggested_actions: Сгенерированные действия
            attempt: Номер текущей попытки (для safety limit)
            previous_feedback: История предыдущего feedback

        Returns:
            ValidatorResult с оценкой и решением
        """
        if attempt >= self.max_attempts:
            logger.warning(
                "Достигнут лимит попыток генерации подсказок",
                extra={"attempt": attempt, "max": self.max_attempts}
            )
            return {
                "is_acceptable": True,
                # При принудительном принятии выставляем умеренную уверенность, а не 0.0
                "confidence": 0.6,
                "feedback": f"Достигнут лимит попыток ({self.max_attempts}). \
                Принимаем текущий вариант как достаточно хороший.",
                "needs_regeneration": False
            }

        if not suggested_actions:
            logger.info("Подсказки отсутствуют, требуется регенерация")
            return {
                "is_acceptable": False,
                "confidence": 1.0,
                "feedback": "Нет конкретных действий для оператора",
                "needs_regeneration": True
            }

        actions_text = "\n".join([f"{i+1}. {action}" for i, action in enumerate(suggested_actions)])

        previous_feedback_text = "\n".join([
            f"- {fb}" for fb in previous_feedback
        ]) if previous_feedback else "Нет"

        user_prompt = VALIDATOR_USER_PROMPT.format(
            user_request=user_request[:300],
            suggested_actions=actions_text,
            previous_feedback=previous_feedback_text
        )

        try:
            result = self._invoke_llm(
                system_prompt=VALIDATOR_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                parser=self.parser,
                agent_name="Validator"
            )

            is_acceptable = result.get("is_acceptable", False)
            confidence = result.get("confidence", 0.5)
            feedback = result.get("feedback", "")

            logger.info(
                "Валидатор завершил проверку",
                extra={
                    "attempt": attempt,
                    "is_acceptable": is_acceptable,
                    "confidence": confidence
                }
            )

            return {
                "is_acceptable": is_acceptable,
                "confidence": confidence,
                "feedback": feedback,
                "needs_regeneration": not is_acceptable and attempt < self.max_attempts
            }

        except Exception as e:
            logger.error(
                "Ошибка валидации подсказок",
                extra={"error": str(e), "attempt": attempt}
            )
            return {
                "is_acceptable": len(suggested_actions) > 0,
                "confidence": 0.3,
                "feedback": f"Ошибка валидации: {str(e)}",
                "needs_regeneration": False
            }

    def process_state(self, state: AgentState) -> AgentState:
        """Обрабатывает состояние: проверяет подсказки и решает о регенерации."""
        metadata = state.get("metadata", {})

        user_request = state.get("user_request", "")
        operator_hints = metadata.get("operator_hints", {})
        suggested_actions = operator_hints.get("suggested_actions", [])

        hints_attempt = metadata.get("hints_generation_attempt", 0)
        feedback_history = metadata.get("validator_feedback_history", [])

        validation = self.validate_hints(
            user_request=user_request,
            suggested_actions=suggested_actions,
            attempt=hints_attempt,
            previous_feedback=feedback_history
        )

        if validation.get("feedback"):
            feedback_history.append(validation["feedback"])

        state["metadata"] = {
            **metadata,
            "validator_result": validation,
            "validator_feedback_history": feedback_history,
        }

        state["current_step"] = "validator_complete"

        logger.info(
            "Валидатор обработал состояние",
            extra={
                "needs_regeneration": validation.get("needs_regeneration", False),
                "attempt": hints_attempt
            }
        )

        return state

