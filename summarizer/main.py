import asyncio
import logging
import json
import os
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from title_generator import generate_chat_title

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KAFKA_URL = os.getenv('KAFKA_URL', 'localhost:9092')
MONGODB_URL = os.getenv('MONGODB_URL', 'mongodb://localhost:27017')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'tech_support')

mongo_client = None
db = None


async def connect_to_mongo():
    """Подключение к MongoDB"""
    global mongo_client, db
    try:
        mongo_client = AsyncIOMotorClient(MONGODB_URL)
        await mongo_client.admin.command('ping')
        db = mongo_client[DATABASE_NAME]
        logger.info("Подключение к MongoDB установлено")
    except Exception as e:
        logger.error(f"Ошибка подключения к MongoDB: {e}")
        raise


async def close_mongo_connection():
    """Закрытие подключения к MongoDB"""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("Подключение к MongoDB закрыто")


async def update_chat_title(user_id: str, title: str) -> bool:
    """
    Обновляет название чата в MongoDB.
    
    Args:
        user_id: ID пользователя
        title: Сгенерированное название
    
    Returns:
        True если обновление прошло успешно
    """
    try:
        collection = db.chats
        
        result = await collection.update_one(
            {"user_id": user_id},
            {"$set": {"title": title}}
        )
        
        if result.modified_count > 0:
            logger.info(f"Название чата обновлено для пользователя {user_id}: '{title}'")
            return True
        else:
            logger.warning(f"Чат не найден для пользователя {user_id}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка обновления названия чата: {e}")
        return False


async def send_title_to_kafka(producer: AIOKafkaProducer, user_id: str, title: str):
    """
    Отправляет сгенерированное название в Kafka.
    
    Args:
        producer: Kafka producer
        user_id: ID пользователя
        title: Сгенерированное название
    """
    try:
        message = {
            "user_id": user_id,
            "title": title
        }
        
        await producer.send_and_wait(
            'chat_title_generated',
            key=user_id.encode('utf-8'),
            value=json.dumps(message).encode('utf-8')
        )
        
        logger.info(f"Название отправлено в Kafka для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки в Kafka: {e}")


async def process_title_request(message: dict, producer: AIOKafkaProducer):
    """
    Обрабатывает запрос на генерацию названия.
    
    Args:
        message: Сообщение из Kafka с полями user_id и first_message
        producer: Kafka producer для отправки результата
    """
    try:
        user_id = message.get('user_id')
        first_message = message.get('first_message')
        
        if not user_id or not first_message:
            logger.warning(f"Неполные данные в сообщении: {message}")
            return
        
        logger.info(f"Генерация названия для пользователя {user_id}")
        logger.info(f"Первое сообщение: {first_message[:100]}...")
        
        title = await generate_chat_title(first_message)
        
        logger.info(f"Сгенерировано название: '{title}'")
        
        await update_chat_title(user_id, title)
        await send_title_to_kafka(producer, user_id, title)
        
    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {e}")


async def kafka_consumer_loop():
    """
    Основной цикл Kafka consumer.
    Слушает топик 'chat_title_request' и генерирует названия чатов.
    """
    consumer = AIOKafkaConsumer(
        'chat_title_request',
        bootstrap_servers=KAFKA_URL,
        group_id='summarizer-consumer-group',
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        max_poll_interval_ms=600000,  
        session_timeout_ms=60000, 
        heartbeat_interval_ms=10000  
    )
    
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_URL,
        compression_type='gzip'
    )
    
    logger.info("Запуск Summarizer Kafka consumer...")
    
    await consumer.start()
    await producer.start()
    
    try:
        logger.info("Ожидание запросов на генерацию названий...")
        
        async for msg in consumer:
            try:
                request = msg.value
                logger.info(f"Получен запрос: {request}")
                
                await process_title_request(request, producer)
                await consumer.commit()
                logger.info("Запрос обработан и закоммичен")
                
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)
                await consumer.commit()
                
    except Exception as e:
        logger.error(f"Критическая ошибка consumer: {e}", exc_info=True)
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Summarizer consumer остановлен")


async def main():
    """Главная функция"""
    try:
        logger.info("Запуск Summarizer микросервиса...")
        logger.info("Использование OpenRouter API для генерации названий")
        
        await connect_to_mongo()
        
        await kafka_consumer_loop()
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        await close_mongo_connection()
        logger.info("Summarizer микросервис остановлен")


if __name__ == "__main__":
    asyncio.run(main())

