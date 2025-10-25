from fastapi import APIRouter, UploadFile, Form, File, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Literal, Dict
from datetime import datetime
from bson import ObjectId
import asyncio
import os
import uuid
from pathlib import Path
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.s3_storage import get_photo_url
from app.services.kafka import update_message_with_ocr
from app.database import get_database
from app.cache import get_active_chat_cached, invalidate_chat_cache
from app.tasks.ocr_tasks import process_image_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])

# Константы для валидации
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 10 * 1024 * 1024))  # 10 MB
ALLOWED_FILE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
RATE_LIMIT = os.getenv("RATE_LIMIT_PER_MINUTE", "60/minute")

limiter = Limiter(key_func=get_remote_address)

# WebSocket connections менеджер
class ConnectionManager:
    """Менеджер WebSocket подключений для real-time уведомлений"""
    
    def __init__(self):
        # chat_id -> список WebSocket подключений
        self.active_connections: Dict[str, list[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, chat_id: str):
        """Подключить нового клиента"""
        await websocket.accept()
        if chat_id not in self.active_connections:
            self.active_connections[chat_id] = []
        self.active_connections[chat_id].append(websocket)
        logger.info(f"🔌 WebSocket подключен к чату {chat_id}")
    
    def disconnect(self, websocket: WebSocket, chat_id: str):
        """Отключить клиента"""
        if chat_id in self.active_connections:
            self.active_connections[chat_id].remove(websocket)
            if not self.active_connections[chat_id]:
                del self.active_connections[chat_id]
        logger.info(f"🔌 WebSocket отключен от чата {chat_id}")
    
    async def send_message(self, chat_id: str, message: dict):
        """Отправить сообщение всем подключенным клиентам чата"""
        if chat_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[chat_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            
            # Удаляем отключенные соединения
            for conn in disconnected:
                self.disconnect(conn, chat_id)
    
    async def broadcast(self, message: dict):
        """Broadcast сообщение всем подключенным клиентам"""
        for chat_id in list(self.active_connections.keys()):
            await self.send_message(chat_id, message)

# Глобальный менеджер подключений
ws_manager = ConnectionManager()

class KafkaMessageData(BaseModel):
    message_id: str
    chat_id: str
    telegram_chat_id: int
    flag: str
    message: str
    photo: Optional[str]
    date: str
    is_read: bool
    merge_text: str


class MessageCreate(BaseModel):
    telegram_chat_id: int
    flag: Literal["operator", "user"]
    message: str
    photo: Optional[str] = None

async def upload_to_s3(file_content: bytes, filename: str) -> str:
    """Асинхронно загружает файл в Minio S3."""
    image_url = await asyncio.to_thread(get_photo_url, file_content, filename)
    return image_url

async def get_active_chat_id(telegram_chat_id: int):
    """
    Получает _id активного чата по telegram_chat_id с кэшированием
    """
    chat_id_str = await get_active_chat_cached(telegram_chat_id)
    if chat_id_str:
        return ObjectId(chat_id_str)
    return None


def validate_file(file: UploadFile, max_size: int = MAX_FILE_SIZE) -> None:
    """
    Валидация загружаемого файла.
    
    Args:
        file: Загружаемый файл
        max_size: Максимальный размер в байтах
    
    Raises:
        HTTPException: Если файл не проходит валидацию
    """
    # Проверка типа файла
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый тип файла: {file.content_type}. "
                   f"Разрешены: {', '.join(ALLOWED_FILE_TYPES)}"
        )
    
    # Проверка имени файла
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла отсутствует")


async def save_message_to_db(message_data: dict):
    """
    Сохраняет сообщение в MongoDB.
    Принимает готовый dict без merge_text.
    Возвращает message_id или None.
    """
    try:
        db = get_database()
        collection = db.messages
        
        if "chat_id" in message_data and isinstance(message_data["chat_id"], str):
            message_data["chat_id"] = ObjectId(message_data["chat_id"])
        
        result = await collection.insert_one(message_data)
        
        if result.inserted_id:
            logger.info(f"Сообщение {result.inserted_id} сохранено в БД для чата {message_data['chat_id']}")
            return str(result.inserted_id)
        return None
    except Exception as e:
        logger.error(f"Ошибка при сохранении сообщения: {e}")
        return None


async def send_to_kafka(topic: str, message_data: KafkaMessageData, partition_key: Optional[str] = None):
    """
    Отправляет сообщение в Kafka с партиционированием.
    
    Args:
        topic: Название топика
        message_data: Данные сообщения
        partition_key: Ключ для партиционирования (по умолчанию chat_id)
    """
    from aiokafka import AIOKafkaProducer
    import json
    
    logger.info(f"Отправка в Kafka, топик '{topic}'")
    
    # Используем chat_id как ключ партиционирования
    key = partition_key or message_data.chat_id
    
    producer = AIOKafkaProducer(
        bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'),
        key_serializer=lambda k: k.encode('utf-8') if k else None,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        compression_type='gzip',  # Сжатие gzip (встроенное в Python)
        max_request_size=int(os.getenv('KAFKA_MAX_REQUEST_SIZE', 10485760)),
        request_timeout_ms=60000
    )
    
    try:
        await producer.start()
        
        await producer.send_and_wait(
            topic,
            key=key,
            value=message_data.model_dump()
        )
        
        logger.info(f"Сообщение {message_data.message_id} отправлено в Kafka '{topic}' (key: {key})")
    except Exception as e:
        logger.error(f"Ошибка отправки в Kafka: {e}")
        # Отправляем в DLQ (Dead Letter Queue)
        await send_to_dlq(topic, message_data, str(e))
        raise
    finally:
        await producer.stop()


async def send_to_dlq(original_topic: str, message_data: dict, error: str):
    """Отправка сообщения в Dead Letter Queue при ошибке"""
    from aiokafka import AIOKafkaProducer
    import json
    
    try:
        dlq_message = {
            "original_topic": original_topic,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
            "data": message_data if isinstance(message_data, dict) else message_data.model_dump()
        }
        
        producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'),
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        await producer.start()
        await producer.send_and_wait('kafka_dlq', value=dlq_message)
        await producer.stop()
        
        logger.warning(f"Сообщение отправлено в DLQ: {original_topic}")
    except Exception as dlq_error:
        logger.error(f"Критическая ошибка: не удалось отправить в DLQ: {dlq_error}")

@router.post("/add_message")
@limiter.limit(RATE_LIMIT)
async def add_message_handler(
    request: Request,
    telegram_chat_id: int = Form(...),
    text: str = Form(...),
    photo: Optional[UploadFile] = File(None) 
):
    """
    Обрабатывает новое сообщение от пользователя.
    
    Логика:
    1. Проверяем активный чат (с кэшированием)
    2. Если есть фото - валидируем и загружаем в S3
    3. Запускаем OCR через Celery (с retry)
    4. Отправляем в Kafka с партиционированием
    """
    photo_url = None
    ocr_task_id = None
    
    # Проверяем активный чат (с кэшированием)
    chat_id = await get_active_chat_id(telegram_chat_id)
    
    if not chat_id:
        raise HTTPException(
            status_code=404,
            detail="Активный чат не найден. Создайте тикет через /ticket"
        )
    
    # Если есть фото - валидируем и загружаем
    ocr_status = "NO_PHOTO"
    
    if photo:
        validate_file(photo)
        file_content = await photo.read()
        
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Файл слишком большой. Максимальный размер: {MAX_FILE_SIZE / (1024*1024):.1f} MB"
            )
        
        if not file_content:
            raise HTTPException(status_code=400, detail="Файл пустой")
        
        photo_url = await upload_to_s3(file_content, photo.filename)
        ocr_status = "OCR_QUEUED"
        
    message_id = str(uuid.uuid4())
    
    if photo_url:
        try:
            task = process_image_task.delay(photo_url, message_id)
            ocr_task_id = task.id
            logger.info(f"OCR задача поставлена в очередь: {ocr_task_id}")
        except Exception as e:
            logger.error(f"Ошибка постановки OCR задачи: {e}")
            ocr_status = "OCR_ERROR"
    
    current_date = datetime.utcnow().isoformat()
    
    # Событие: TicketCreated
    kafka_data = KafkaMessageData(
        message_id=message_id,
        chat_id=str(chat_id),
        telegram_chat_id=telegram_chat_id,
        flag="user",
        message=text,
        photo=photo_url,
        date=current_date,
        is_read=False,
        merge_text=text  
    )
    
    await send_to_kafka("ticket_created", kafka_data, partition_key=str(chat_id))
    try:

        await send_to_kafka(
            topic="websocket_notifications",
            message_data=kafka_data,
            partition_key=str(chat_id)
        )
        logger.info(f"Событие для WebSocket отправлено в Kafka для чата {chat_id}")

    except Exception as e:
        logger.error(f"Ошибка отправки WebSocket уведомления через Kafka: {e}")
    
    logger.info(f"Сообщение {message_id} обработано. OCR: {ocr_status}, Task: {ocr_task_id}")
    
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Message sent to Kafka",
            "message_id": message_id,
            "photo_url": photo_url,
            "ocr_status": ocr_status,
            "ocr_task_id": ocr_task_id,
            "telegram_chat_id": telegram_chat_id
        }
    )


@router.post("/message/create")
async def create_message(message: str = Form(...),telegram_chat_id: int = Form(...),photo: Optional[UploadFile] = File(None),flag: str = Form(...)):
    """
    Создает новое сообщение в чате (универсальная ручка для оператора/пользователя).
    Используется для сообщений от оператора.
    telegram_chat_id: int
    flag: Literal["operator", "user"]
    message: str
    photo: Optional[str] = None
    Args:
        message_data: Данные сообщения (telegram_chat_id, flag, message, photo)
    
    Returns:
        JSON с созданным сообщением
    """
    try:
        # Проверяем существует ли активный чат
        chat_id = await get_active_chat_id(telegram_chat_id)
        
        if not chat_id:
            raise HTTPException(
                status_code=404,
                detail="Активный чат не найден"
            )
        
        # Формируем данные
        current_date = datetime.utcnow().isoformat()
        message_id = str(uuid.uuid4())
        photo_url = None  # Инициализируем здесь для доступа во всей функции
        
        # Данные для MongoDB
        # message_for_db = {
        #     "chat_id": chat_id,
        #     "telegram_chat_id": message_data.telegram_chat_id,
        #     "flag": message_data.flag,
        #     "message": message_data.message,
        #     "photo": message_data.photo,
        #     "date": current_date,
        #     "is_read": False
        # }
        
        # # Сохраняем в MongoDB
        # message_id = await save_message_to_db(message_for_db)
        
        if not message_id:
            raise HTTPException(
                status_code=500,
                detail="Не удалось создать сообщение"
            )
        
        if flag == 'operator':
            try:
                # Используем chat_id как ключ партиционирования для гарантии порядка
                key = str(chat_id)
                if photo:
                    # Валидация файла
                    validate_file(photo)
                    
                    # Читаем содержимое с проверкой размера
                    file_content = await photo.read()
                    
                    if len(file_content) > MAX_FILE_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Файл слишком большой. Максимальный размер: {MAX_FILE_SIZE / (1024*1024):.1f} MB"
                        )
                    
                    if not file_content:
                        raise HTTPException(status_code=400, detail="Файл пустой")
                    
                    # Загружаем в Minio S3
                    photo_url = await upload_to_s3(file_content, photo.filename)

                # Создаем объект KafkaMessageData или простой dict
                kafka_payload = {
                    "message_id": message_id,
                    "chat_id": str(chat_id),
                    "telegram_chat_id": telegram_chat_id,
                    "flag": flag,
                    "message": message,
                    "photo": photo_url,
                    "date": current_date, 
                    "is_read": False,
                    "merge_text": message
                }
                
                # Создаем экземпляр модели Pydantic для отправки через вашу функцию
                kafka_data_model = KafkaMessageData(**kafka_payload)
                # Отправляем в оба топика:
                # - ticket_created для сохранения в БД
                # - operator_replies для отправки в Telegram
                await asyncio.gather(
                    send_to_kafka("ticket_created", kafka_data_model, partition_key=key),
                    send_to_kafka("operator_replies", kafka_data_model, partition_key=key)
                )
                
                logger.info(f"Сообщение оператора {message_id} отправлено в топики 'ticket_created' и 'operator_replies'")

            except Exception as e:
                logger.error(f"Ошибка отправки сообщения оператора в Kafka: {e}")
                raise
        
        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "message": "Сообщение успешно создано",
                "message_id": message_id,
                "photo_url": photo_url  
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при создании сообщения: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.post("/update-ocr")
async def update_ocr_text(external_message_id: str = Form(...), ocr_text: str = Form(...)):
    """
    Обновляет сообщение результатом OCR обработки.
    Вызывается при получении события из Kafka (топик ocr_processed).
    
    Args:
        external_message_id: ID сообщения из Kafka
        ocr_text: Текст распознанный OCR
    
    Returns:
        JSON с результатом обновления
    """
    try:
        success = await update_message_with_ocr(external_message_id, ocr_text)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Сообщение не найдено"
            )
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "OCR текст успешно добавлен",
                "external_message_id": external_message_id
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обновлении OCR текста: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/messages/{telegram_chat_id}")
async def get_chat_messages(
    telegram_chat_id: int, 
    limit: int = 50, 
    before_date: Optional[str] = None,
    active_only: bool = True
):
    """
    Получает историю сообщений чата с cursor-based пагинацией.
    
    Args:
        telegram_chat_id: ID чата в Telegram
        limit: Количество сообщений (макс 100)
        before_date: ISO дата для пагинации (получить сообщения до этой даты)
        active_only: Получать только сообщения активного чата
    
    Returns:
        JSON со списком сообщений и cursor для следующей страницы
    """
    try:
        limit = min(limit, 100)
        
        db = get_database()
        
        query = {}
        
        if active_only:
            chat_id = await get_active_chat_id(telegram_chat_id)
            
            if not chat_id:
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "count": 0,
                        "messages": [],
                        "next_cursor": None,
                        "info": "Нет активного чата"
                    }
                )
            
            query["chat_id"] = chat_id
        else:
            query["telegram_chat_id"] = telegram_chat_id
        
        # Cursor-based пагинация
        if before_date:
            query["date"] = {"$lt": before_date}
        
        collection = db.messages
        cursor = collection.find(
            query,
            {"_id": 0}
        ).sort("date", -1).limit(limit + 1)  # +1 для определения наличия следующей страницы
        
        messages = await cursor.to_list(length=limit + 1)
        
        # Определяем есть ли еще сообщения
        has_more = len(messages) > limit
        if has_more:
            messages = messages[:limit]
        
        # Возвращаем в прямом порядке (от старых к новым)
        messages.reverse()
        
        # Cursor для следующей страницы
        next_cursor = messages[0]["date"] if messages and has_more else None
        
        logger.info(f"Получено {len(messages)} сообщений для чата {telegram_chat_id}")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "count": len(messages),
                "messages": messages,
                "next_cursor": next_cursor,
                "has_more": has_more
            }
        )
    
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )



