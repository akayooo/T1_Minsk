import asyncio
import logging
import json
from typing import Optional
from datetime import datetime
from bson import ObjectId
import os

from app.database import get_database

logger = logging.getLogger(__name__)


async def check_message_exists(external_message_id: str) -> bool:
    """
    Проверяет существует ли сообщение с таким external_message_id.
    Для обеспечения идемпотентности consumer.
    """
    try:
        db = get_database()
        collection = db.messages
        
        existing = await collection.find_one({"external_message_id": external_message_id})
        return existing is not None
    except Exception as e:
        logger.error(f"Ошибка проверки существования сообщения: {e}")
        return False

async def update_message_with_ocr(external_message_id: str, ocr_text: str) -> bool:
    """
    Обновляет сообщение результатом OCR обработки.
    Вызывается при получении события из Kafka (топик ocr_processed).
    """
    try:
        db = get_database()
        collection = db.messages
        
        result = await collection.update_one(
            {"external_message_id": external_message_id},
            {
                "$set": {
                    "ocr_text": ocr_text,
                    "ocr_processed_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"OCR текст добавлен к сообщению {external_message_id}")
            return True
        
        logger.warning(f"Сообщение {external_message_id} не найдено для обновления OCR текста")
        return False
    except Exception as e:
        logger.error(f"Ошибка при обновлении OCR текста: {e}")
        return False



async def update_chat_title(user_id: str, title: str) -> bool:
    """
    Обновляет название тикета в MongoDB.
    Вызывается при получении события из Kafka с сгенерированным названием.
    """
    try:
        db = get_database()
        collection = db.chats
        
        chat = await collection.find_one({"user_id": user_id})
        
        if not chat:
            logger.warning(f"Чат с user_id {user_id} не найден в базе")
            return False
        
        logger.info(f"Найден чат для user_id {user_id}, is_active={chat.get('is_active')}")
        
        result = await collection.update_one(
            {"user_id": user_id, "is_active": True},
            {"$set": {"title": title}}
        )
        
        if result.modified_count > 0:
            logger.info(f"Название тикета обновлено для пользователя {user_id}: '{title}'")
            return True
        
        logger.warning(f"Чат для пользователя {user_id} не активен или уже имеет это название")
        return False
    except Exception as e:
        logger.error(f"Ошибка при обновлении названия тикета: {e}")
        return False


async def kafka_consumer_ocr_processed():
    """
    Kafka consumer для топика 'ocr_processed'.
    Обновляет сообщения результатами OCR обработки.
    """
    from aiokafka import AIOKafkaConsumer
    
    consumer = AIOKafkaConsumer(
        'ocr_processed',
        bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'),
        group_id='backend-ocr-consumer-group',
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    logger.info("Запуск Backend Kafka consumer для 'ocr_processed'...")
    
    await consumer.start()
    try:
        logger.info("Backend consumer 'ocr_processed' запущен и ожидает сообщения")
        
        async for msg in consumer:
            try:
                ocr_event = msg.value
                # { "message_id": "...", "ocr_text": "..." }
                
                logger.info(f"Получено OCR событие для message_id: {ocr_event.get('message_id')}")
                
                success = await update_message_with_ocr(
                    ocr_event["message_id"],
                    ocr_event["ocr_text"]
                )
                
                # Коммитим offset
                await consumer.commit()
                
                if success:
                    logger.info(f"OCR текст обновлен и закоммичен для {ocr_event.get('message_id')}")
                else:
                    logger.warning(f"Не удалось обновить OCR текст для {ocr_event.get('message_id')}")
                    
            except Exception as e:
                logger.error(f"Ошибка обработки OCR события: {e}")
                await consumer.commit()
                
    except Exception as e:
        logger.error(f"Критическая ошибка OCR consumer: {e}")
    finally:
        await consumer.stop()
        logger.info("Backend consumer 'ocr_processed' остановлен")


async def kafka_consumer_chat_title_generated():
    """
    Kafka consumer для топика 'chat_title_generated'.
    Обновляет названия тикета в MongoDB.
    """
    from aiokafka import AIOKafkaConsumer
    
    consumer = AIOKafkaConsumer(
        'chat_title_generated',
        bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'),
        group_id='backend-title-consumer-group',
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    
    logger.info("Запуск Backend Kafka consumer для 'chat_title_generated'...")
    
    await consumer.start()
    try:
        logger.info("Backend consumer 'chat_title_generated' запущен и ожидает сообщения")
        
        async for msg in consumer:
            try:
                title_event = msg.value
                # { "user_id": "...", "title": "..." }
                
                logger.info(f"Получено событие с названием чата для user_id: {title_event.get('user_id')}")
                
                success = await update_chat_title(
                    title_event["user_id"],
                    title_event["title"]
                )
                
                # Коммитим offset
                await consumer.commit()
                
                if success:
                    logger.info(f"Название чата обновлено и закоммичено для {title_event.get('user_id')}")
                else:
                    logger.warning(f"Не удалось обновить название чата для {title_event.get('user_id')}")
                    
            except Exception as e:
                logger.error(f"Ошибка обработки события названия: {e}")
                await consumer.commit()
                
    except Exception as e:
        logger.error(f"Критическая ошибка title consumer: {e}")
    finally:
        await consumer.stop()
        logger.info("Backend consumer 'chat_title_generated' остановлен")

async def run_consumers():
    """Запускает Kafka consumers фоном"""
    
    logger.info("Запуск Kafka Consumers")
    
    try:
        await asyncio.gather(
            kafka_consumer_ocr_processed(),
            kafka_consumer_chat_title_generated()
        )
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("Kafka consumers остановлены")

