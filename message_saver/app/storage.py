from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from typing import Optional
from .config import MONGODB_URL
import logging
import os
import json

mongo_client = AsyncIOMotorClient(MONGODB_URL)
db = mongo_client.tech_support
collection = db.messages
chats_collection = db.chats

logger = logging.getLogger('storage')

async def check_message_exists(external_message_id: str) -> bool:
    """
    Проверяет существует ли сообщение с таким external_message_id.
    Для обеспечения идемпотентности consumer.
    """
    try:
        
        existing = await collection.find_one({"external_message_id": external_message_id})
        return existing is not None
    except Exception as e:
        logger.error(f"Ошибка проверки существования сообщения: {e}")
        return False


async def is_first_user_message(chat_id: ObjectId) -> bool:
    """
    Проверяет, является ли это первым сообщением пользователя в чате.
    """
    try:
        count = await collection.count_documents({
            "chat_id": chat_id,
            "flag": "user"
        })
        return count == 0
    except Exception as e:
        logger.error(f"Ошибка проверки первого сообщения: {e}")
        return False


async def get_user_id_by_chat_id(chat_id: ObjectId) -> Optional[str]:
    """
    Получает user_id по chat_id.
    """
    try:
        chat = await chats_collection.find_one({"_id": chat_id})
        return chat.get("user_id") if chat else None
    except Exception as e:
        logger.error(f"Ошибка получения user_id: {e}")
        return None


async def send_title_request_to_kafka(user_id: str, first_message: str):
    """
    Отправляет запрос на генерацию названия чата в Kafka.
    """
    from aiokafka import AIOKafkaProducer
    from .config import KAFKA_URL
    
    try:
        message = {
            "user_id": user_id,
            "first_message": first_message
        }
        
        producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_URL,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        await producer.start()
        try:
            await producer.send_and_wait(
                'chat_title_request',
                key=user_id.encode('utf-8'),
                value=message
            )
            logger.info(f"Запрос на генерацию названия отправлен для пользователя {user_id}")
        finally:
            await producer.stop()
            
    except Exception as e:
        logger.error(f"Ошибка отправки запроса на генерацию названия: {e}")


async def save_message(message_data: dict) -> Optional[str]:
    """
    Идемпотентное сохранение сообщения из Kafka в MongoDB.
    
    Принимает из Kafka:
    {
        message_id, chat_id, telegram_chat_id, flag, message, 
        photo, date, is_read, merge_text
    }
    
    Сохраняет в MongoDB:
    {
        external_message_id (для идемпотентности),
        chat_id, telegram_chat_id, flag, message, 
        photo, date, is_read, ocr_text (null)
    }
    
    Returns:
        ObjectId сохраненного сообщения или None если уже существует
    """
    try:
        # Проверка идемпотентности
        if await check_message_exists(message_data["message_id"]):
            logger.warning(f"Сообщение {message_data['message_id']} уже обработано")
            return None
      
        
        # Конвертируем chat_id из строки в ObjectId
        chat_object_id = ObjectId(message_data["chat_id"]) if isinstance(message_data["chat_id"], str) else message_data["chat_id"]
        
        # Формируем документ для MongoDB (без merge_text)
        message_to_save = {
            "external_message_id": message_data["message_id"],  
            "chat_id": chat_object_id,
            "telegram_chat_id": message_data["telegram_chat_id"],
            "flag": message_data["flag"],
            "message": message_data["message"],
            "photo": message_data.get("photo"),
            "date": message_data["date"],
            "is_read": message_data.get("is_read", False),
            "ocr_text": None  # Заполнится из события OCR
        }
        
        # Проверяем, является ли это первым сообщением пользователя
        is_first = False
        if message_data["flag"] == "user":
            is_first = await is_first_user_message(chat_object_id)
        
        # Атомарно сохраняем
        result = await collection.insert_one(message_to_save)
        
        if result.inserted_id:
            logger.info(f"Сообщение {result.inserted_id} сохранено (external_id: {message_data['message_id']})")
            
            # Если это первое сообщение пользователя, отправляем запрос на генерацию названия
            if is_first and message_data["flag"] == "user":
                user_id = await get_user_id_by_chat_id(chat_object_id)
                if user_id:
                    await send_title_request_to_kafka(user_id, message_data["message"])
                    logger.info(f"Запрос на генерацию названия отправлен для первого сообщения")
            
            return str(result.inserted_id)
        return None
    except Exception as e:
        logger.error(f"Ошибка при сохранении сообщения из Kafka: {e}")
        return None
