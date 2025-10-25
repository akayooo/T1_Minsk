"""
Memory controller for extracting and deduplicating knowledge from dialogues.

The MemoryController class is responsible for extracting facts from dialogues,
assessing them, filtering, and deduplicating before saving to a vector database.
It now supports checking memory for duplicates and replacing old knowledge with new.
"""

import json
import re
import time
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

from agent_system.rag import RetrieverController
from agent_system.utils.logger import logger

from .promts import build_system_prompt, build_user_prompt

try:
    from langchain_openai import ChatOpenAI
    _HAS_LANGCHAIN = True
except ImportError:
    ChatOpenAI = object
    _HAS_LANGCHAIN = False

RoleLiteral = Literal["user", "operator"]


class KnowledgeItem(BaseModel):
    """Data model for a unit of knowledge extracted from a dialogue."""

    key: int = Field(..., description="Index of the fragment in the original dialogue")
    role: RoleLiteral = Field(..., description="Role of the fragment's author")
    title: str = Field(..., description="A short title for the knowledge")
    sub_title: str = Field(..., description="A detailed description of the knowledge")
    knowledge: str = Field(..., description="The formulation of the extracted knowledge")
    user_id: int = Field(..., description="User ID for grouping")

    @field_validator("title", "sub_title", "knowledge")
    @classmethod
    def _strip_spaces(cls, v: str) -> str:
        """Strips leading/trailing whitespace from string fields."""
        return v.strip()

    @field_validator("key")
    @classmethod
    def _non_negative_key(cls, v: int) -> int:
        """Ensures the key is a non-negative integer."""
        if v < 0:
            raise ValueError("key cannot be negative")
        return v


class _LLMCandidate(BaseModel):
    """Internal model for representing a knowledge candidate from the LLM."""

    key: int
    role: RoleLiteral
    title: str
    sub_title: str
    knowledge: str
    keep: bool = Field(..., description="Recommendation to keep the knowledge")
    score: int = Field(..., ge=0, le=100, description="Suitability score")
    reason: str = Field(..., description="Justification for the score")


class MemoryController:
    """Controller for extracting and deduplicating knowledge from dialogues."""

    def __init__(
        self,
        llm: Optional[ChatOpenAI] = None,
        base_url: str = "https://llm.t1v.scibox.tech/v1",
        api_key: Optional[str] = None,
        model: str = "Qwen2.5-72B-Instruct-AWQ",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        request_timeout: int = 30,
        delay_between_requests: float = 0.5,
        max_retries: int = 3,
        min_keep_score: int = 70,
        rag_controller: Optional[RetrieverController] = None,
    ) -> None:
        """Initializes the MemoryController.

        Args:
            llm: An optional pre-configured LangChain ChatOpenAI instance.
            base_url: The base URL for the OpenRouter API.
            api_key: The API key for OpenRouter.
            model: The name of the model to use for processing.
            temperature: The generation temperature.
            max_tokens: The maximum number of tokens in the response.
            request_timeout: The request timeout in seconds.
            delay_between_requests: The delay between retry attempts.
            max_retries: The maximum number of retries.
            min_keep_score: The minimum score to keep a knowledge item.
            rag_controller: The RAG controller for memory operations.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.delay_between_requests = delay_between_requests
        self.max_retries = max_retries
        self.min_keep_score = min_keep_score
        self.rag_controller = rag_controller

        if llm:
            self.llm = llm
        else:
            if not _HAS_LANGCHAIN:
                logger.error("langchain-openai is not installed. Please install it with 'pip install langchain-openai'")
                raise ImportError("langchain-openai is required. Please install it with 'pip install langchain-openai'")
            self.llm = ChatOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.request_timeout,
            )
        logger.info(f"MemoryController initialized with model: {self.model}")

    def extract_and_validate(self, dialogue: Sequence[Dict[str, str]], user_id: int = 0) -> List[KnowledgeItem]:
        """Extracts, validates, and deduplicates knowledge from a dialogue.

        Args:
            dialogue: A sequence of messages, each as a dict with 'role' and 'content'.
            user_id: The ID of the user for grouping knowledge.

        Returns:
            A list of validated and filtered KnowledgeItem objects.
        """
        if not dialogue:
            logger.warning("extract_and_validate called with an empty dialogue.")
            return []

        logger.info(f"Starting knowledge extraction user_id: {user_id} from a dialogue of {len(dialogue)} messages.")

        norm_dialogue = self._normalize_roles(dialogue)
        candidates = self._llm_extract_candidates(norm_dialogue)
        kept_candidates = self._filter_candidates(candidates)

        items = [KnowledgeItem(user_id=user_id, **k) for k in kept_candidates]
        logger.info(f"Extracted {len(items)} high-quality knowledge items.")

        if self.rag_controller and items:
            self._deduplicate_and_update_memory(items, user_id)

        return items

    def _deduplicate_and_update_memory(self, new_items: List[KnowledgeItem], user_id: int) -> None:
        """Checks for duplicates in memory and replaces old knowledge with new.

        Args:
            new_items: A list of new knowledge items to check.
            user_id: The user ID to filter the memory search.
        """
        if not self.rag_controller:
            logger.warning("RAG controller not set, skipping deduplication.")
            return

        logger.info(f"Starting memory deduplication for user_id: {user_id}")

        for item in new_items:
            try:
                similar_records = self.rag_controller.search_long_term_memory(
                    query=item.knowledge,
                    user_id=user_id,
                    limit=5
                )

                if similar_records:
                    logger.info(f"Found {len(similar_records)} similar records for knowledge titled '{item.title}'.")
                    for record in similar_records:
                        if record.payload and "id" in record.payload:
                            old_id = record.payload["id"]
                            deleted = self.rag_controller.delete_memory_by_id(old_id)
                            if deleted:
                                logger.info(f"Deleted old record with ID {old_id}")
                            else:
                                logger.warning(f"Failed to delete record with ID {old_id}")
                    logger.info(f"Replacing old knowledge with new for user_id: {user_id}")

            except Exception as e:
                logger.exception(f"Error during knowledge deduplication for user_id {user_id}: {e}")

    @staticmethod
    def _normalize_roles(dialogue: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        """Normalizes roles in a dialogue to standard 'user' or 'operator' values."""
        role_map = {
            "user": "user", "client": "user",
            "operator": "operator", "assistant": "operator",
            "agent": "operator", "support": "operator", "system": "operator",
        }
        result = []
        for m in dialogue:
            role = (m.get("role") or "").strip().lower()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role_norm = role_map.get(role, "operator")
            result.append({"role": role_norm, "content": content})
        return result

    def _llm_extract_candidates(self, dialogue: Sequence[Dict[str, str]]) -> List[_LLMCandidate]:
        """Gets knowledge candidates from the LLM with suitability scores."""
        sys_prompt = build_system_prompt()
        user_prompt = build_user_prompt(dialogue)
        logger.debug("Sending request to LLM for knowledge extraction.")

        attempt = 0
        last_error: Optional[Exception] = None
        while attempt < self.max_retries:
            try:
                resp = self.llm.invoke([
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ])

                raw_text = getattr(resp, "content", "") or (resp if isinstance(resp, str) else "")
                data = self._safe_json_extract(raw_text)

                candidates_data = data.get("candidates", [])
                if not isinstance(candidates_data, list):
                    logger.warning(f"LLM returned 'candidates' not as a list: {type(candidates_data)}")
                    return []

                return [_LLMCandidate(**c) for c in candidates_data]
            except Exception as e:
                last_error = e
                attempt += 1
                logger.warning(f"LLM extraction attempt {attempt}/{self.max_retries} failed: {e}")
                time.sleep(self.delay_between_requests * (attempt + 1))

        logger.error(f"Failed to get candidates from LLM after {self.max_retries} attempts.")
        raise RuntimeError(f"Could not get candidates from LLM after {self.max_retries} attempts: {last_error}") \
        from last_error

    def _filter_candidates(self, candidates: Sequence[_LLMCandidate]) -> List[Dict[str, Any]]:
        """Filters candidates based on quality and relevance."""
        kept = []
        for c in candidates:
            if not c.keep or c.score < self.min_keep_score:
                logger.debug(f"Filtering out candidate '{c.title}' with score {c.score} and keep={c.keep}.")
                continue

            if not all([c.title, c.sub_title, c.knowledge]):
                logger.debug(f"Filtering out candidate with missing fields: {c.title}")
                continue

            text_lower = c.knowledge.lower()
            ephemeral_markers = ["сейчас", "прямо сейчас", "в данный момент", "сегодня"]
            evergreen_markers = ["кажд", "обычно", "регулярно", "как правило"]

            is_ephemeral = any(mark in text_lower for mark in ephemeral_markers)
            is_evergreen = any(mark in text_lower for mark in evergreen_markers)

            if is_ephemeral and not is_evergreen:
                logger.debug(f"Filtering out ephemeral candidate: {c.title}")
                continue

            kept.append({
                "key": c.key,
                "role": c.role,
                "title": c.title.strip()[:120],
                "sub_title": c.sub_title.strip()[:400],
                "knowledge": c.knowledge.strip(),
            })
        return kept

    @staticmethod
    def _safe_json_extract(text: str) -> Dict[str, Any]:
        """Safely extracts JSON from the model's response text."""
        if not text:
            return {"candidates": []}

        # Try to find a JSON object or array
        json_match = re.search(r"\s*(\{.*\}|\[.*\])\s*", text, re.DOTALL)
        if not json_match:
            logger.warning("No JSON object or array found in the LLM response.")
            return {"candidates": []}

        json_str = json_match.group(1)

        try:
            data = json.loads(json_str)
            if isinstance(data, list):
                return {"candidates": data}
            if isinstance(data, dict):
                return data if "candidates" in data else {"candidates": [data]}
            return {"candidates": []}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from LLM response: {e}. Content: '{json_str[:200]}...'",
            extra={"raw_text": text})
            # Attempt to repair common issues (though this is brittle)
            repaired_str = json_str.replace("\n", " ").replace("\r", " ").replace("True", "true"). \
            replace("False", "false")
            try:
                data = json.loads(repaired_str)
                if isinstance(data, list):
                    return {"candidates": data}
                return data if isinstance(data, dict) and "candidates" in data else {"candidates": []}
            except json.JSONDecodeError:
                logger.error("JSON repair failed.", extra={"raw_text": text})

        return {"candidates": []}

__all__ = ["MemoryController", "KnowledgeItem"]
