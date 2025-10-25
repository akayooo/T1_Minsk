"""Агент генерации подсказок для операторов службы поддержки.

Анализирует запрос пользователя и найденные документы из RAG,
генерирует конкретные рекомендации для оператора по решению проблемы.
"""

import logging
from typing import List, Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from agent_system.agents.base_agent import BaseLLMAgent
from agent_system.source.prompts import (
HINTS_GENERATOR_SYSTEM_PROMPT,
HINTS_GENERATOR_USER_PROMPT,
HINTS_REGENERATE_PROMPT,
)
from agent_system.state import AgentState, HintsResult

logger = logging.getLogger(__name__)


class HintsGeneratorAgent(BaseLLMAgent):
	"""Генерирует подсказки для оператора службы поддержки."""

	def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None) -> None:
		super().__init__(llm, model_name)
		self.parser = JsonOutputParser()

	def _get_document_title(self, doc: dict) -> str:
		"""Извлекает заголовок документа из payload."""
		payload = (doc.get("payload", {}) or {})
		return payload.get("title") or payload.get("source") or f"doc_{doc.get('id')}"

	def _get_document_knowledge(self, doc: dict) -> str:
		"""Извлекает содержимое документа из payload."""
		payload = (doc.get("payload", {}) or {})
		return payload.get("knowledge") or payload.get("text", "")

	def _format_documents_summary(self, documents: List[dict], source_type: str = "RAG") -> str:
		"""Форматирует документы в читаемый вид для LLM."""
		if not documents:
			return ""
		
		formatted_docs = []
		for d in documents:
			score = d.get('score', 0)
			title = self._get_document_title(d)
			knowledge = self._get_document_knowledge(d)
			formatted_docs.append(f"[{source_type} {score:.2f}] {title}: {knowledge}")
		
		return "\n".join(formatted_docs)

	def _combine_documents_sections(self, rag_docs: str, memory_docs: str) -> str:
		"""Объединяет документы из RAG и памяти в единый текст."""
		sections = []
		
		if rag_docs.strip():
			sections.append(f"База знаний:\n{rag_docs}")
		
		if memory_docs.strip():
			sections.append(f"История пользователя:\n{memory_docs}")
		
		return "\n\n".join(sections) if sections else ""

	def _select_relevant_docs_from_reranked(self, documents: List[dict], limit: int = 3) -> List[str]:
		"""Возвращает список человеко-читаемых заголовков по топ-N документам из RAG после rerank."""
		selected = []
		for d in (documents or [])[:limit]:
			title = self._get_document_title(d)
			selected.append(str(title))
		return selected

	def generate_hints(
		self,
		user_request: str,
		documents: List[dict],
		memory_documents: List[dict] = None
	) -> HintsResult:
		"""Генерирует подсказки для оператора на основе данных RAG и памяти.

		Args:
			user_request: Исходный запрос пользователя
			documents: Релевантные документы после reranker
			memory_documents: Документы из памяти пользователя

		Returns:
			HintsResult с подсказками для оператора
		"""
		if not documents:
			logger.warning("Нет документов для генерации подсказок")
			return {
				"suggested_actions": ["Запросить дополнительную информацию у пользователя"],
				"relevant_docs": []
			}

		# Формируем документы из RAG и памяти
		rag_docs_summary = self._format_documents_summary(documents, "RAG")
		memory_docs_summary = self._format_documents_summary(memory_documents, "Memory")

		# Объединяем документы
		docs_summary = self._combine_documents_sections(rag_docs_summary, memory_docs_summary)

		if not docs_summary.strip():
			logger.warning("docs_summary пуст, используем заглушку")
			docs_summary = "Нет доступных документов"

		user_prompt = HINTS_GENERATOR_USER_PROMPT.format(
			user_request=user_request,
			documents=docs_summary
		)

		try:
			result = self._invoke_llm(
				system_prompt=HINTS_GENERATOR_SYSTEM_PROMPT,
				user_prompt=user_prompt,
				parser=self.parser,
				agent_name="HintsGenerator"
			)

			suggested_actions = result.get("suggested_actions", [])
			relevant_docs_llm = result.get("relevant_docs", [])
			relevant_docs = self._select_relevant_docs_from_reranked(documents, limit=3)
			if not relevant_docs:
				relevant_docs = relevant_docs_llm

			logger.info(
				"Подсказки сгенерированы",
				extra={
					"actions_count": len(suggested_actions),
					"docs_from_rerank": relevant_docs
				}
			)

			return {
				"suggested_actions": suggested_actions,
				"relevant_docs": relevant_docs
			}

		except Exception as e:
			logger.error(f"Ошибка генерации подсказок: {e}")
			return {
				"suggested_actions": ["Обратиться к документации", "Эскалировать запрос"],
				"relevant_docs": self._select_relevant_docs_from_reranked(documents, limit=3)
			}

	def regenerate_hints(
		self,
		user_request: str,
		documents: List[dict],
		previous_actions: List[str],
		validator_feedback: str,
		hints_history: List[dict],
		memory_documents: List[dict] = None
	) -> HintsResult:
		"""Регенерирует подсказки с учетом feedback от валидатора.

		Args:
			user_request: Исходный запрос пользователя
			documents: Документы из RAG
			previous_actions: Предыдущие подсказки
			validator_feedback: Feedback от валидатора
			hints_history: История попыток генерации
			memory_documents: Документы из памяти пользователя

		Returns:
			HintsResult с улучшенными подсказками
		"""
		
		# Формируем документы из RAG и памяти
		rag_docs_summary = self._format_documents_summary(documents, "RAG")
		memory_docs_summary = self._format_documents_summary(memory_documents, "Memory")

		# Объединяем документы
		docs_summary = self._combine_documents_sections(rag_docs_summary, memory_docs_summary)

		previous_actions_text = "\n".join([
			f"{i+1}. {action}" for i, action in enumerate(previous_actions)
		]) if previous_actions else "Нет предыдущих попыток"

		history_text = "\n".join([
			f"Попытка {i+1}: {len(h.get('actions', []))} действий"
			for i, h in enumerate(hints_history)
		]) if hints_history else "Нет истории"

		user_prompt = HINTS_REGENERATE_PROMPT.format(
			user_request=user_request,
			previous_actions=previous_actions_text,
			validator_feedback=validator_feedback,
			documents=docs_summary,
			hints_history=history_text
		)

		try:
			result = self._invoke_llm(
				system_prompt=HINTS_GENERATOR_SYSTEM_PROMPT,
				user_prompt=user_prompt,
				parser=self.parser,
				agent_name="HintsGenerator (regenerate)"
			)

			suggested_actions = result.get("suggested_actions", [])
			relevant_docs = self._select_relevant_docs_from_reranked(documents, limit=3)
			logger.info(
				"Подсказки регенерированы",
				extra={
					"actions_count": len(suggested_actions),
					"docs_from_rerank": relevant_docs
				}
			)

			return {
				"suggested_actions": suggested_actions,
				"relevant_docs": relevant_docs
			}

		except Exception as e:
			logger.error(f"Ошибка регенерации подсказок: {e}")
			return {
				"suggested_actions": previous_actions if previous_actions else ["Эскалировать запрос"],
				"relevant_docs": self._select_relevant_docs_from_reranked(documents, limit=3)
			}

	def process_state(self, state: AgentState) -> AgentState:
		"""Обрабатывает состояние: генерирует или регенерирует подсказки."""
		metadata = state.get("metadata", {})

		user_request = state.get("user_request", "")
		documents = metadata.get("rag_docs_reranked", [])
		memory_documents = metadata.get("memory_docs", [])

		validator_result = metadata.get("validator_result")

		if validator_result and not validator_result.get("is_acceptable", True):
			logger.info("Регенерация подсказок на основе feedback валидатора")

			previous_hints = metadata.get("operator_hints", {})
			previous_actions = previous_hints.get("suggested_actions", [])
			feedback = validator_result.get("feedback", "")
			hints_history = metadata.get("hints_history", [])

			hints = self.regenerate_hints(
				user_request=user_request,
				documents=documents,
				previous_actions=previous_actions,
				validator_feedback=feedback,
				hints_history=hints_history,
				memory_documents=memory_documents
			)
		else:
			logger.info("Первичная генерация подсказок")
			hints = self.generate_hints(
				user_request=user_request,
				documents=documents,
				memory_documents=memory_documents
			)

		hints_history = metadata.get("hints_history", [])
		hints_history.append({
			"attempt": metadata.get("hints_generation_attempt", 0),
			"actions": hints.get("suggested_actions", [])
		})

		new_attempt = metadata.get("hints_generation_attempt", 0) + 1

		state["metadata"] = {
			**metadata,
			"operator_hints": hints,
			"hints_generation_attempt": new_attempt,
			"hints_history": hints_history
		}

		state["current_step"] = "hints_complete"

		logger.info(
			f"Генератор подсказок обработал состояние (попытка {new_attempt})",
			extra={"actions_count": len(hints.get("suggested_actions", [])),
			"relevant_docs": hints.get("relevant_docs", [])}
		)

		return state
