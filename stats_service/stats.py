import asyncio
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict
from datetime import datetime

from aiokafka import AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient
from contextlib import asynccontextmanager
from bson import ObjectId
import os
from typing import List

MONGO_URL = os.getenv("MONGODB_URL","mongodb+srv://neartemuzerdb:iRKQx2R5F7VswigP@cluster0.niges.mongodb.net/")
KAFKA_URL = os.getenv("KAFKA_URL")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReviewData(BaseModel):
    """Модель для валидации данных из Kafka."""
    chat_id: str
    rating: float = Field(...)
    comment: str | None = None
    operator_id: str
    flag: str
    model_config = ConfigDict(extra='allow')

class ReviewInDB(ReviewData):
    """Модель для отображения данных из MongoDB (включая _id)."""
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

mongo_client = AsyncIOMotorClient(MONGO_URL)

async def consume_and_save():
    """Слушает Kafka и сохраняет сообщения в MongoDB."""
    consumer = AIOKafkaConsumer(
        "reviews_topic",
        bootstrap_servers=KAFKA_URL,
        group_id="review_mongo_savers",
        auto_offset_reset='earliest'
    )
    await consumer.start()
    logger.info(f"Kafka Consumer запущен")
    
    db = mongo_client.tech_support
    collection = db.stats
    
    try:
        async for msg in consumer:
            logger.info(f"Получено сообщение: {msg.value.decode('utf-8')}")
            try:
                data = json.loads(msg.value.decode('utf-8'))
                review_data = ReviewData(**data)
                review_data.closed_at = datetime.utcnow().isoformat()
                
                await collection.insert_one(review_data.dict())
                
                logger.info(f"Отзыв для продукта {review_data.chat_id} сохранен в MongoDB.")

            except json.JSONDecodeError:
                logger.error(f"Ошибка декодирования JSON: {msg.value.decode('utf-8')}")
            except Exception as e:
                logger.error(f"Произошла ошибка при обработке сообщения: {e}")
    finally:
        await consumer.stop()
        logger.info("Kafka Consumer остановлен.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск фоновой задачи для Kafka Consumer...")
    kafka_task = asyncio.create_task(consume_and_save())
    
    yield 

    logger.info("Остановка Kafka Consumer...")
    kafka_task.cancel()
    mongo_client.close()
    logger.info("Приложение остановлено.")

class OperatorStats(BaseModel):
    operator_id: str = Field(..., description="ID оператора")
    total_stats: int = Field(..., description="Общее количество оценок (статистик) у оператора")
    average_rating: Optional[float] = Field(None, description="Средний рейтинг оператора")
    rating_distribution: Dict[str, int] = Field({}, description="Распределение оценок")

app = FastAPI(title="Reviews Service with MongoDB", lifespan=lifespan)

@app.get(
    "/stats/{operator_id}",
    response_model=OperatorStats,
    tags=["Stats"],
    summary="Получить статистику по оператору"
)
async def get_operator_stats(operator_id: str):
    db = mongo_client.tech_support
    chats_collection = db.stats
    pipeline = [
        {"$match": {
            "operator_id": operator_id,
            "rating": {"$ne": None}
        }},
        {"$group": {
            "_id": "$operator_id",
            "average_rating": {"$avg": "$rating"},
            "ratings": {"$push": "$rating"},
            "total_stats": {"$sum": 1} 
        }},

        {"$project": {
            "_id": 0,
            "operator_id": "$_id",
            "average_rating": 1,
            "total_stats": 1, 
            "rating_distribution": {
                "$arrayToObject": {
                    "$map": {
                        "input": {"$setUnion": ["$ratings", []]},
                        "as": "r",
                        "in": {
                            "k": {"$toString": "$$r"},
                            "v": {"$size": {"$filter": {"input": "$ratings", "cond": {"$eq": ["$$this", "$$r"]}}}}
                        }
                    }
                }
            }
        }}
    ]


    try:
        cursor = chats_collection.aggregate(pipeline)
        result = await cursor.to_list(length=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при выполнении агрегации в БД: {e}")

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Оператор с ID '{operator_id}' не найден или у него нет чатов."
        )

    return result[0]

class StatItem(BaseModel):
    id: str = Field(..., alias="_id")
    chat_id: str
    operator_id: str
    rating: Optional[int] = None
    comment: Optional[str] = None
    flag: Optional[str] = None
    closed_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True
        json_encoders = {ObjectId: str}


@app.get(
    "/list-stats/{operator_id}",
    response_model=List[StatItem],
    tags=["Stats"],
    summary="Получить последние 5 записей статистики по дате закрытия"
)
async def get_latest_operator_stats_by_close_date(operator_id: str):
    """
    Возвращает список из 5 последних документов статистики для указанного оператора,
    отсортированных по полю `closed_at` в обратном порядке (от новых к старым).
    """
    db = mongo_client.tech_support
    stats_collection = db.stats

    pipeline = [
        {"$match": {
            "operator_id": operator_id,
        }},
        
        {"$sort": {
            "closed_at": -1 
        }},

        {"$limit": 5}
    ]

    try:
        cursor = stats_collection.aggregate(pipeline)
        latest_stats = await cursor.to_list(length=None)
        
        # Конвертируем ObjectId в строки
        for stat in latest_stats:
            if '_id' in stat:
                stat['_id'] = str(stat['_id'])
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при выполнении запроса: {e}")

    if not latest_stats:
        raise HTTPException(
            status_code=404,
            detail=f"Статистика для оператора с ID '{operator_id}' не найдена."
        )

    return latest_stats
