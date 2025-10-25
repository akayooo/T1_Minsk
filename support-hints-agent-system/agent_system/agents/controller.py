"""Агент Контроллер (Controller) — проверка качества результатов RAG.

Анализирует результаты reranker и решает, достаточно ли релевантны документы
для ответа на пользовательский запрос. Если нет — инициирует переформулирование.
"""

import logging
from typing import List, Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from agent_system.agents.base_agent import BaseLLMAgent
from agent_system.source.prompts import CONTROLLER_SYSTEM_PROMPT, CONTROLLER_USER_PROMPT
from agent_system.state import AgentState, ControllerResult

logger = logging.getLogger(__name__)


class ControllerAgent(BaseLLMAgent):
	"""Проверяет качество результатов RAG и решает о необходимости переформулирования."""

	def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None, max_iterations: int = 3) -> None:
		super().__init__(llm, model_name)
		self.parser = JsonOutputParser()
		self.max_iterations = max_iterations

	def evaluate_results(
		self,
		original_query: str,
		current_query: str,
		documents: List[dict],
		iteration: int,
		previous_attempts: List[dict],
		memory_docs: Optional[List[dict]] = None
	) -> ControllerResult:
		"""Оценивает результаты RAG и решает, нужно ли переформулировать запрос.

		Args:
			original_query: Исходный пользовательский запрос
			current_query: Текущий нормализованный запрос
			documents: Документы после reranker
			iteration: Номер текущей итерации
			previous_attempts: История предыдущих попыток
			memory_docs: (Игнорируется) — контроллер работает автономно, без памяти

		Returns:
			ControllerResult с решением и рекомендациями
		"""
		if iteration >= self.max_iterations:
			logger.warning(
				"Достигнут лимит итераций",
				extra={"iteration": iteration, "max": self.max_iterations}
			)
			return {
				"is_satisfactory": True,
				"confidence": 0.0,
				"reasoning": f"Достигнут максимальный лимит итераций ({self.max_iterations})",
				"suggestions": "",
				"needs_reformulation": False
			}

		if not documents:
			logger.info("Документы не найдены, требуется переформулирование")
			needs_reformulation = iteration < self.max_iterations
			return {
				"is_satisfactory": False,
				"confidence": 1.0,
				"reasoning": "Документы не найдены",
				"suggestions": "Попробуйте использовать более общие или альтернативные формулировки ключевых понятий",
				"needs_reformulation": needs_reformulation
			}

		try:
			input_docs_log = []
			for d in documents:
				payload = d.get("payload", {}) or {}
				input_docs_log.append({
					"id": d.get("id"),
					"score": d.get("score"),
					"title": payload.get("title"),
					"source": payload.get("source")
				})
			logger.info(
				"Controller input",
				extra={
					"iteration": iteration,
					"docs_count": len(documents),
					"docs": input_docs_log,
					"original_query": original_query,
					"current_query": current_query,
					"previous_attempts_count": len(previous_attempts or [])
				}
			)
		except Exception:
			logger.exception("Ошибка при логировании документов")
			pass

		docs_summary_lines = []
		for d in documents:
			score = d.get('score', 0) or 0
			payload = d.get('payload', {}) or {}
			knowledge = payload.get('knowledge', '')[:150]
			docs_summary_lines.append(f"- [{score:.4f}] {knowledge}")
		
		docs_summary = "\n".join(docs_summary_lines)

		previous_queries = "\n".join([
			f"{i+1}. {attempt.get('query', 'N/A')}"
			for i, attempt in enumerate(previous_attempts or [])
		]) if previous_attempts else "Нет предыдущих попыток"

		user_prompt = CONTROLLER_USER_PROMPT.format(
			original_query=original_query,
			current_query=current_query,
			documents=docs_summary,
			iteration=iteration,
			max_iterations=self.max_iterations,
			previous_queries=previous_queries
		)

		try:
			try:
				docs_scores = [float(d.get("score", 0) or 0.0) for d in documents]
			except Exception:
				docs_scores = []
			prompt_preview = user_prompt[:500]
			logger.info(
				"Controller prompt prepared",
				extra={
					"iteration": iteration,
					"docs_count": len(documents),
					"docs_scores": docs_scores,
					"prompt_preview": prompt_preview
				}
			)
			result = self._invoke_llm(
				system_prompt=CONTROLLER_SYSTEM_PROMPT,
				user_prompt=user_prompt,
				parser=self.parser,
				agent_name="Controller"
			)

			is_satisfactory = result.get("is_satisfactory")
			if is_satisfactory is None:
				logger.warning("LLM не вернул поле 'is_satisfactory', используем False")
				is_satisfactory = False

			confidence = result.get("confidence", 0.5)
			reasoning = result.get("reasoning", "")
			suggestions = result.get("suggestions", "")
			decision = {
				"is_satisfactory": is_satisfactory,
				"confidence": confidence,
				"reasoning": reasoning,
				"suggestions": suggestions,
				"needs_reformulation": not is_satisfactory and iteration < self.max_iterations
			}
			logger.info(
				"Controller decision",
				extra={
					"iteration": iteration,
					"decision": decision
				}
			)
			return decision

		except Exception as e:
			logger.error(
				"Ошибка оценки контроллера",
				extra={"error": str(e), "iteration": iteration}
			)
			return {
				"is_satisfactory": len(documents) > 0,
				"confidence": 0.3,
				"reasoning": f"Ошибка оценки: {str(e)}",
				"suggestions": "",
				"needs_reformulation": False
			}

	def process_state(self, state: AgentState, memory_docs: Optional[List[dict]] = None) -> AgentState:
		"""Обрабатывает состояние: оценивает результаты и решает о продолжении.

		Args:
			state: Текущее состояние агента
			memory_docs: Игнорируется
		"""
		metadata = state.get("metadata", {})

		original_query = state.get("user_request", "")
		finder_result = metadata.get("finder", {})
		current_query = finder_result.get("normalized_query", "")
		documents = metadata.get("rag_docs_reranked", [])
		iteration = metadata.get("iteration_count", 0)
		query_history = metadata.get("query_history", [])

		evaluation = self.evaluate_results(
			original_query=original_query,
			current_query=current_query,
			documents=documents,
			iteration=iteration,
			previous_attempts=query_history,
			memory_docs=None
		)

		state["metadata"] = {
			**metadata,
			"controller_evaluation": evaluation,
		}

		state["current_step"] = "controller_complete"

		logger.info(
			"Контроллер обработал состояние",
			extra={
				"needs_reformulation": evaluation.get("needs_reformulation", False),
				"iteration": iteration
			}
		)

		return state

