"""
Пакет memory: извлечение и валидация долговременных знаний из диалогов.
"""

from .memory_controller import KnowledgeItem, MemoryController

__all__ = ["MemoryController", "KnowledgeItem"]
__version__ = "0.1.0"
