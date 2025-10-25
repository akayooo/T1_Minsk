"""
Скрипт для создания и настройки коллекций в Qdrant.

Создает две коллекции: knowledge_base для базы знаний с гибридным поиском
и long_term_memory для хранения памяти разговоров с индексами по полям.

Обновлено для модели xlm-r-100langs-bert-base-nli-stsb-mean-tokens (размерность 768).
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import logging

from qdrant_client import QdrantClient, models
import pandas as pd

from agent_system.rag.controller import RetrieverController, SparseEncoder
from agent_system.utils.model_loader import load_deeppavlov_bert


logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_COLLECTION = "knowledge_base"
LONG_TERM_MEMORY_COLLECTION = "long_term_memory"

VECTOR_PARAMS = models.VectorParams(
    size=768,
    distance=models.Distance.COSINE
)


def setup_knowledge_base(client: QdrantClient, collection_name: str) -> None:
    """
    Создает коллекцию для базы знаний с поддержкой гибридного поиска.

    Настраивает плотные (768-dim) и разреженные векторы для модели
    xlm-r-100langs-bert-base-nli-stsb-mean-tokens, а также индексы
    для эффективного поиска по ключевым полям.

    Args:
        client: Клиент подключения к Qdrant
        collection_name: Название коллекции для создания
    """
    try:
        collections_response = client.get_collections()
        existing_collections = [c.name for c in collections_response.collections]

        if collection_name in existing_collections:
            logger.info("Коллекция '%s' уже существует, пересоздаем", collection_name)
            client.delete_collection(collection_name=collection_name)

        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "default": VECTOR_PARAMS
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=200)
        )
        logger.info("Коллекция '%s' создана с поддержкой гибридного поиска", collection_name)

        logger.info("Настройка индексов для коллекции '%s'", collection_name)
        client.create_payload_index(
            collection_name=collection_name,
            field_name="key",
            field_schema=models.PayloadSchemaType.INTEGER
        )
        logger.info("Индекс для поля 'key' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="title",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=50,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'title' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="sub_title",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=100,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'sub_title' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="knowledge",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=500,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'knowledge' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="source",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=100,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'source' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="id",
            field_schema=models.PayloadSchemaType.INTEGER
        )
        logger.info("Индекс для поля 'id' создан")

    except Exception as e:
        logger.error("Ошибка при настройке коллекции '%s': %s", collection_name, e)


def setup_long_term_memory(client: QdrantClient, collection_name: str) -> None:
    """
    Создает коллекцию для долгосрочной памяти с индексами по ключевым полям.

    Настраивает плотные векторы (768-dim) для модели
    xlm-r-100langs-bert-base-nli-stsb-mean-tokens и индексы
    для эффективного поиска по пользователям, знаниям и временным меткам.

    Args:
        client: Клиент подключения к Qdrant
        collection_name: Название коллекции для создания
    """
    try:
        collections_response = client.get_collections()
        existing_collections = [c.name for c in collections_response.collections]

        if collection_name not in existing_collections:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VECTOR_PARAMS,
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        always_ram=True
                    )
                ),
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100)
            )
            logger.info("Коллекция '%s' успешно создана", collection_name)
        else:
            logger.info("Коллекция '%s' уже существует", collection_name)

        logger.info("Настройка индексов для коллекции '%s'", collection_name)

        client.create_payload_index(
            collection_name=collection_name,
            field_name="knowledge",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=500,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'knowledge' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="title",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=100,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'title' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="sub_title",
            field_schema=models.TextIndexParams(
                type="text",
                tokenizer=models.TokenizerType.WORD,
                min_token_len=2,
                max_token_len=200,
                lowercase=True
            )
        )
        logger.info("Индекс для поля 'sub_title' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="user_id",
            field_schema=models.PayloadSchemaType.INTEGER
        )
        logger.info("Индекс для поля 'user_id' создан")

        client.create_payload_index(
            collection_name=collection_name,
            field_name="id",
            field_schema=models.PayloadSchemaType.INTEGER
        )
        logger.info("Индекс для поля 'id' создан")

    except Exception as e:
        logger.error("Ошибка при настройке коллекции '%s': %s", collection_name, e)


def download_to_base():
    dense_encoder = load_deeppavlov_bert()
    logger.info("Loading data and initializing SparseEncoder...")
    excel_file_path = "agent_system/service/smart_support_vtb_belarus_faq_final.xlsx"
    try:
        df = pd.read_excel(excel_file_path)
        df.fillna('', inplace=True)
    except FileNotFoundError:
        logger.error(f"Excel file not found at: {excel_file_path}")
        return

    corpus = (df["Пример вопроса"] + " " + df["Шаблонный ответ"]).tolist()
    sparse_encoder = SparseEncoder(corpus=corpus)

    controller = RetrieverController(
        client=client,
        dense_encoder=dense_encoder,
        sparse_encoder=sparse_encoder
    )

    logger.warning("Clearing the knowledge base before population.")
    controller.clear_knowledge_base()

    documents_to_add = [
        {
            "knowledge": row["Шаблонный ответ"],
            "title": row["Основная категория"],
            "sub_title": row["Подкатегория"],
        }
        for _, row in df.iterrows()
    ]

    if documents_to_add:
        logger.info(f"Adding {len(documents_to_add)} documents to the knowledge base.")
        controller.add_to_knowledge_base(documents=documents_to_add, source="T1")
        logger.info("Knowledge base population complete.")


if __name__ == "__main__":
    """Основная функция для создания и настройки коллекций."""
    try:
        client = QdrantClient(host="localhost", port=6333)
        client.get_collections()
        logger.info("Успешное подключение к Qdrant")
    except Exception as e:
        logger.error("Не удалось подключиться к Qdrant: %s", e)
        exit(1)

    logger.info("Запуск процесса создания/обновления коллекций в Qdrant")
    setup_knowledge_base(client=client, collection_name=KNOWLEDGE_BASE_COLLECTION)
    setup_long_term_memory(client=client, collection_name=LONG_TERM_MEMORY_COLLECTION)
    download_to_base()
    logger.info("Знания загружены в Qdrant")
    logger.info("Процесс завершен")
