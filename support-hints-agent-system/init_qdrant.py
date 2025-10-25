#!/usr/bin/env python3
"""
Скрипт для инициализации Qdrant коллекций при запуске ML сервиса.
Запускается перед основным приложением.
"""

import os
import sys
import time
import logging
from qdrant_client import QdrantClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импортируем функции создания коллекций
from agent_system.service.qudrant_db_creator import (
    setup_knowledge_base, 
    setup_long_term_memory,
    KNOWLEDGE_BASE_COLLECTION,
    LONG_TERM_MEMORY_COLLECTION
)


def wait_for_qdrant(qdrant_url: str, max_retries: int = 30, delay: int = 2):
    """
    Ожидает готовности Qdrant сервера.
    
    Args:
        qdrant_url: URL для подключения к Qdrant
        max_retries: Максимальное количество попыток подключения
        delay: Задержка между попытками в секундах
    """
    logger.info(f"Ожидание готовности Qdrant по адресу: {qdrant_url}")
    
    for attempt in range(max_retries):
        try:
            client = QdrantClient(url=qdrant_url)
            client.get_collections()
            logger.info("Qdrant готов к работе!")
            return client
        except Exception as e:
            logger.warning(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                logger.error("Не удалось подключиться к Qdrant после всех попыток")
                raise


def init_qdrant_collections():
    """
    Инициализирует коллекции в Qdrant.
    """
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    
    try:
        # Ждем готовности Qdrant
        client = wait_for_qdrant(qdrant_url)
        
        logger.info("Начинаем инициализацию коллекций Qdrant...")
        
        # ВАЖНО: Удаляем старую коллекцию long_term_memory если она существует с неправильной размерностью
        try:
            collections_response = client.get_collections()
            existing_collections = [c.name for c in collections_response.collections]
            
            if LONG_TERM_MEMORY_COLLECTION in existing_collections:
                logger.warning(f"Коллекция {LONG_TERM_MEMORY_COLLECTION} уже существует. Удаляем для пересоздания с правильной размерностью (768)...")
                client.delete_collection(collection_name=LONG_TERM_MEMORY_COLLECTION)
                logger.info(f"Коллекция {LONG_TERM_MEMORY_COLLECTION} удалена")
        except Exception as e:
            logger.warning(f"Не удалось удалить старую коллекцию: {e}")
        
        # Создаем коллекцию для базы знаний
        setup_knowledge_base(client, KNOWLEDGE_BASE_COLLECTION)
        
        # Создаем коллекцию для долгосрочной памяти
        setup_long_term_memory(client, LONG_TERM_MEMORY_COLLECTION)
        
        logger.info("Инициализация коллекций Qdrant завершена успешно!")
        
    except Exception as e:
        logger.error(f"Ошибка при инициализации Qdrant: {e}")
        sys.exit(1)


if __name__ == "__main__":
    init_qdrant_collections()
