"""Определения состояний и типизированных результатов агентов.

Содержит типы состояния графа (`AgentState`) и результирующие структуры
для классификации, извлечения сущностей, сводной экстракции и искателя.
"""

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


def merge_metadata(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Объединяет metadata из параллельных узлов.
    При конфликте правый (более поздний) источник имеет приоритет.
    """
    if not left:
        return right
    if not right:
        return left
    merged = {**left, **right}
    return merged


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_request: str
    extracted_data: Optional[Dict[str, Any]]
    current_step: str
    metadata: Annotated[Dict[str, Any], merge_metadata]
    iteration_count: int


class ClassificationResult(TypedDict):
    category: str
    priority: str
    sentiment: str


class EntityExtractionResult(TypedDict):
    entities: Dict[str, Optional[str]]


class ExtractionResult(TypedDict):
    category: str
    priority: str
    sentiment: str
    entities: Dict[str, Optional[str]]


class FinderResult(TypedDict):
    normalized_query: str
    original_query: str
    memory_query: str


class QdrantPayload(TypedDict):
    text: str
    source: str
    page_number: Optional[int]


class RerankedDoc(TypedDict):
    id: str
    score: float
    payload: QdrantPayload


class RerankResult(TypedDict):
    results: List[RerankedDoc]


class ControllerResult(TypedDict):
    is_satisfactory: bool
    confidence: float
    reasoning: str
    suggestions: str
    needs_reformulation: bool


class HintsResult(TypedDict):
    suggested_actions: List[str]
    relevant_docs: List[str]


class ValidatorResult(TypedDict):
    is_acceptable: bool
    confidence: float
    feedback: str
    needs_regeneration: bool
