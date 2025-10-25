"""
RAG (Retrieval-Augmented Generation) система.

Этот пакет содержит компоненты для обработки документов,
создания векторных представлений и поиска по базе знаний.
"""

from .controller import RetrieverController
from .fragments_creator import AsyncDocumentProcessor, ChunkingParams, process_text_chunks

__all__ = [
    "AsyncDocumentProcessor",
    "ChunkingParams",
    "process_text_chunks",
    "RetrieverController"
]
