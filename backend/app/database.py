import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import logging

# load_dotenv()

logger = logging.getLogger(__name__)

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "tech_support")

class MongoDB:
    client: AsyncIOMotorClient = None
    
mongodb = MongoDB()


async def connect_to_mongo():
    """Подключение к MongoDB"""
    try:
        mongodb.client = AsyncIOMotorClient(MONGODB_URL)
        await mongodb.client.admin.command('ping')
    except Exception as e:
        logger.error(f"Ошибка подключения к MongoDB: {e}")
        raise


async def close_mongo_connection():
    """Закрытие подключения к MongoDB"""
    try:
        if mongodb.client:
            mongodb.client.close()
            logger.info("Подключение к MongoDB закрыто")
    except Exception as e:
        logger.error(f"Ошибка при закрытии подключения к MongoDB: {e}")


def get_database():
    """Получение экземпляра базы данных"""
    return mongodb.client[DATABASE_NAME]

