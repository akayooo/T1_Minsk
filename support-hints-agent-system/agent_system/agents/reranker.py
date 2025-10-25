"""Агент ReRanker — валидация и ранжирование результатов ретривера.

Принимает документы формата Qdrant {id, score, payload} и возвращает их в том же
формате, сохраняя score и payload. Модель возвращает только порядок id;
агент собирает финальную структуру на основе исходных документов.
"""

import json
from typing import Dict, List, Optional, Tuple

from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agent_system.agents.base_agent import BaseLLMAgent
from agent_system.source.prompts import RERANKER_SYSTEM_PROMPT, RERANKER_USER_PROMPT
from agent_system.state import RerankedDoc, RerankResult
from agent_system.utils.logger import logger


class ReRankId(BaseModel):
	id: str = Field(description="Идентификатор документа")


class ReRankIds(BaseModel):
	results: List[ReRankId]


class ReRankerAgent(BaseLLMAgent):
	"""Выполняет reranking/validation/formatting над выдачей ретривера."""

	def __init__(self, llm: Optional[ChatOpenAI] = None, model_name: str = None) -> None:
		super().__init__(llm, model_name)
		self.parser = JsonOutputParser(pydantic_object=ReRankIds)

	def rerank(self, query: str, docs: List[RerankedDoc]) -> RerankResult:
		"""Возвращает документы в формате Qdrant, сохраняя score и payload."""
		if not docs:
			return {"results": []}

		id_to_doc: Dict[str, RerankedDoc] = {str(d.get("id")): d for d in docs}

		docs_for_llm = []
		for d in docs[:7]:
			payload = d.get("payload", {}) or {}
			text = payload.get("knowledge") or payload.get("text", "")
			docs_for_llm.append({
				"id": d.get("id"),
				"score": d.get("score", None),
				"text": text
			})

		try:
			structured_preview = [
				{
					"id": d.get("id"),
					"score": d.get("score", None),
					"payload": (d.get("payload", {}) or {})
				}
				for d in docs[:10]
			]
			logger.info(f"ReRanker входные документы (count={len(docs)}): \
			{json.dumps(structured_preview, ensure_ascii=False)}")
		except Exception:
			logger.exception("Ошибка при логировании документов")
			pass
		docs_text = json.dumps(docs_for_llm, ensure_ascii=False, indent=2)
		user_prompt = RERANKER_USER_PROMPT.format(query=query, docs=docs_text)

		try:
			result = self._invoke_llm(
				system_prompt=RERANKER_SYSTEM_PROMPT,
				user_prompt=user_prompt,
				parser=self.parser,
				agent_name="ReRanker",
			)

			items = result.get("results") or []
			ids = [str(it.get("id", "")) for it in items if isinstance(it, dict)]

			ranked: List[RerankedDoc] = [id_to_doc[i] for i in ids if i in id_to_doc]

			input_ids = [d["id"] for d in docs]
			filtered_out = [doc_id for doc_id in input_ids if doc_id not in ids]

			if not ranked:
				logger.warning("ReRanker не вернул документов, используем fallback")
				# Устойчивый fallback: сортируем по наличию и значению score, иначе сохраняем порядок
				def score_key(x: dict) -> Tuple[int, float]:
					try:
						s = x.get("score")
						return (0, float(s)) if s is not None else (1, 0.0)
					except Exception:
						return (1, 0.0)
				ranked = sorted(docs, key=score_key, reverse=True)

			logger.info(
				"ReRanker завершил работу",
				extra={
					"input_count": len(docs),
					"output_count": len(ranked),
					"filtered_count": len(filtered_out)
				}
			)
			return {"results": ranked}

		except Exception as e:
			logger.warning("ReRanker fallback к сортировке", extra={"error": str(e)})
			def score_key(x: dict) -> Tuple[int, float]:
				try:
					s = x.get("score")
					return (0, float(s)) if s is not None else (1, 0.0)
				except Exception:
					return (1, 0.0)
			fallback = sorted(docs, key=score_key, reverse=True)
			return {"results": fallback}
