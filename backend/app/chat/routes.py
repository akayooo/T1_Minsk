from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel,  Field
from typing import Optional
from datetime import datetime
import logging
import os
import json
from pymongo import ReturnDocument
from aiokafka import AIOKafkaProducer

from app.database import get_database
from app.auth.routes import verify_token
from app.cache import invalidate_chat_cache
from app.ml.routes import get_messages_and_memorize, classify_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatCreate(BaseModel):
    telegram_chat_id: int
    user_id: str
    first_message: Optional[str] = None  


class ChatAssign(BaseModel):
    chat_id: str
    operator_id: str

async def send_review_to_kafka(chat_id: str, rating: int, operator_id: str, comment: str,flag: str):
    """
    Отправляет оценку и комментарий в топик 'reviews_topic' в Kafka.

    Args:
        user_id: ID пользователя, чей чат был оценен.
        rating: Оценка от 1 до 10.
        comment: Необязательный текстовый комментарий.
    """
    # Создаем экземпляр продюсера
    producer = AIOKafkaProducer(
        bootstrap_servers=os.getenv('KAFKA_URL', 'localhost:9092'),
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
    )
    
    # Запускаем продюсер
    await producer.start()
    try:
        # Формируем сообщение
        message = {
            "chat_id": chat_id,
            "rating": rating,
            "comment": comment,
            "operator_id": operator_id,
            "flag": flag 
        }
        
        # Отправляем сообщение и ждем подтверждения
        await producer.send_and_wait(
            'reviews_topic',  
            value=message,
            key=chat_id.encode("utf-8")
        )
        logger.info(f"Отзыв с оценкой {rating} успешно отправлен в Kafka.")

    except Exception as e:
        logger.error(f"Ошибка при отправке отзыва в Kafka {e}")
    finally:
        await producer.stop()
        logger.info("Kafka Producer для отправки отзыва остановлен.")

async def send_title_request_to_kafka(user_id: str, first_message: str):
    """
    Отправляет запрос на генерацию названия тикета в Kafka.
    
    Args:
        user_id: ID пользователя
        first_message: Первое сообщение пользователя
    """
    
    try:
        message = {
            "user_id": user_id,
            "first_message": first_message
        }
        
        producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_URL', 'localhost:9092'),
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


async def send_first_message_to_kafka(chat_id: str, telegram_chat_id: int, user_id: str, message: str):
    """
    Отправляет первое сообщение пользователя в Kafka для сохранения в БД.
    
    Args:
        chat_id: ID чата в MongoDB
        telegram_chat_id: ID чата в Telegram
        user_id: ID пользователя
        message: Текст первого сообщения
    """
    import uuid
    
    try:
        message_data = {
            "message_id": str(uuid.uuid4()),
            "chat_id": chat_id,
            "telegram_chat_id": telegram_chat_id,
            "flag": "user",
            "message": message,
            "photo": None,
            "date": datetime.utcnow().isoformat(),
            "is_read": False,
            "merge_text": message
        }
        
        producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_URL', 'localhost:9092'),
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
        )
        
        await producer.start()
        try:
            await producer.send_and_wait(
                'messages',
                key=chat_id.encode('utf-8'),
                value=message_data
            )
            logger.info(f"Первое сообщение отправлено в Kafka для чата {chat_id}")
        finally:
            await producer.stop()
            
    except Exception as e:
        logger.error(f"Ошибка отправки первого сообщения в Kafka: {e}")


async def get_chat_by_id(chat_id: str) -> Optional[dict]:
    """Получает чат по ID"""
    try:
        db = get_database()
        collection = db.chats
        
        chat = await collection.find_one(
            {"chat_id": chat_id},
            {"_id": 0}
        )
        
        return chat
    except Exception as e:
        logger.error(f"Ошибка при получении чата: {e}")
        return None


async def get_chat_by_user(user_id: str) -> Optional[dict]:
    """Получает чат по user_id"""
    try:
        db = get_database()
        collection = db.chats
        
        chat = await collection.find_one(
            {"user_id": user_id, "is_active": True},
            {"_id": 0}
        )
        
        return chat
    except Exception as e:
        logger.error(f"Ошибка при получении чата по user_id: {e}")
        return None


@router.post("/create")
async def create_chat(chat_data: ChatCreate):
    """
    Создает новый чат при создании тикета пользователем.
    operator_id изначально устанавливается в None.
    
    Args:
        chat_data: Данные для создания чата (telegram_chat_id, user_id)
    
    Returns:
        JSON с информацией о созданном чате
    """
    try:
        existing_chat = await get_chat_by_user(chat_data.user_id)
        
        if existing_chat:
            logger.info(f"Чат для пользователя {chat_data.user_id} уже существует")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "success": True,
                    "message": "Чат уже существует",
                    "chat": existing_chat
                }
            )
        
        print(chat_data.first_message)
        db = get_database()
        collection = db.chats
        
        # Классифицируем вопрос только если есть первое сообщение
        main_category = None
        subcategory = None
        if chat_data.first_message:
            try:
                main_category, subcategory = classify_question(chat_data.first_message)
            except Exception as e:
                logger.error(f"Ошибка классификации: {e}")
                # Продолжаем создание чата даже если классификация не удалась
        
        new_chat = {
            "telegram_chat_id": chat_data.telegram_chat_id,
            "user_id": chat_data.user_id,
            "operator_id": None,
            "created_at": datetime.utcnow().isoformat(),
            "assigned_at": None,
            "is_active": True,
            "status": "pending",  
            "title": "Новое обращение",
            "main_category": main_category,
            "subcategory": subcategory
        }
        
        result = await collection.insert_one(new_chat)
        
        if result.inserted_id:
            new_chat["chat_id"] = str(result.inserted_id)
            new_chat.pop("_id", None)
            
            await invalidate_chat_cache(chat_data.telegram_chat_id)
            
            if chat_data.first_message:
                # Отправляем запрос на генерацию названия
                await send_title_request_to_kafka(chat_data.user_id, chat_data.first_message)
                
                # Отправляем первое сообщение в Kafka для сохранения в БД
                await send_first_message_to_kafka(
                    chat_id=str(result.inserted_id),
                    telegram_chat_id=chat_data.telegram_chat_id,
                    user_id=chat_data.user_id,
                    message=chat_data.first_message
                )
            
            logger.info(f"Создан новый чат для пользователя {chat_data.user_id}")
            
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "success": True,
                    "message": "Чат успешно создан",
                    "chat": new_chat
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось создать чат"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при создании чата: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.post("/assign")
async def assign_operator(
    assignment: ChatAssign,
    payload: dict = Depends(verify_token)
):
    """
    Назначает оператора на чат (берет тикет в работу).
    Присваивает operator_id в существующем чате.
    
    Args:
        assignment: Данные для назначения (chat_id, operator_id)
        payload: JWT токен оператора
    
    Returns:
        JSON с обновленной информацией о чате
    """
    try:
        logger.info(f"Назначение оператора {assignment.operator_id} на чат {assignment.chat_id}")
        
        db = get_database()
        collection = db.chats
        
        # Ищем АКТИВНЫЙ чат (важно для случаев с несколькими чатами одного пользователя)
        chat = await collection.find_one({
            "user_id": assignment.chat_id,
            "is_active": True
        })
        logger.info(f"Найден чат: {chat}")
        
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Активный чат не найден"
            )
        
        # Проверяем, не назначен ли уже этот АКТИВНЫЙ чат
        if chat.get("operator_id") is not None and chat.get("status") == "assigned":
            logger.warning(f"Чат {assignment.chat_id} уже назначен оператору {chat['operator_id']}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Чат уже назначен оператору {chat['operator_id']}"
            )
        
        # Обновляем только АКТИВНЫЙ чат
        result = await collection.update_one(
            {
                "user_id": assignment.chat_id,
                "is_active": True
            },
            {
                "$set": {
                    "operator_id": assignment.operator_id,
                    "assigned_at": datetime.utcnow().isoformat(),
                    "status": "assigned"
                }
            }
        )
        
        if result.modified_count > 0:
            updated_chat = await collection.find_one(
                {"user_id": assignment.chat_id},
                {"_id": 0}
            )
            
            logger.info(f"Оператор {assignment.operator_id} назначен на чат {assignment.chat_id}")
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "success": True,
                    "message": "Оператор успешно назначен на чат",
                    "chat": updated_chat
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось назначить оператора"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при назначении оператора: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/user/{user_id}")
async def get_user_chat(user_id: str):
    """
    Получает активный чат пользователя с историей сообщений.
    
    Args:
        user_id: ID пользователя (telegram user id)
    
    Returns:
        JSON с информацией о чате и историей сообщений
    """
    try:
        db = get_database()
        chats_collection = db.chats
        messages_collection = db.messages
        
        chat = await chats_collection.find_one(
            {"user_id": user_id, "is_active": True}
        )
        
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Активный чат не найден"
            )
        
        chat_id = chat.pop("_id")
        chat["chat_id"] = str(chat_id)
        
        messages_cursor = messages_collection.find(
            {"chat_id": chat_id},
            {"external_message_id": 0}
        ).sort("date", 1)  
        
        messages = await messages_cursor.to_list(length=100)
        
        formatted_messages = []
        for msg in messages:
            photo_url = msg.get("photo")
            formatted_messages.append({
                "id": str(msg.get("_id")),
                "role": "user" if msg["flag"] == "user" else "assistant",
                "content": msg.get("message", ""),  
                "imageUrl": photo_url if photo_url else None,
                "serverImageUrl": photo_url if photo_url else None,
                "timestamp": msg.get("date")
            })
        
        chat["messages"] = formatted_messages
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "chat": chat,
                "messages": formatted_messages,
                "title": chat.get("title", "Без названия"),
                "createdAt": chat.get("created_at"),
                "updatedAt": chat.get("created_at")
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении чата: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/check_active/{telegram_chat_id}")
async def check_active_chat(telegram_chat_id: int):
    """
    Проверяет наличие активного чата для пользователя по telegram_chat_id.
    
    Args:
        telegram_chat_id: ID чата в Telegram
    
    Returns:
        JSON с флагом has_active_chat
    """
    try:
        db = get_database()
        chats_collection = db.chats
        
        # Ищем активный чат по telegram_chat_id
        chat = await chats_collection.find_one(
            {"telegram_chat_id": telegram_chat_id, "is_active": True}
        )
        
        has_active = chat is not None
        
        logger.info(f"Проверка активного чата для telegram_chat_id={telegram_chat_id}: {has_active}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "has_active_chat": has_active,
                "chat_id": str(chat["_id"]) if chat else None
            }
        )
    
    except Exception as e:
        logger.error(f"Ошибка при проверке активного чата: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/pending")
async def get_pending_chats(payload: dict = Depends(verify_token)):
    """
    Получает список чатов ожидающих назначения оператора.
    Доступно только авторизованным операторам.
    
    Args:
        payload: JWT токен оператора
    
    Returns:
        JSON со списком ожидающих чатов с первым сообщением
    """
    try:
        db = get_database()
        chats_collection = db.chats
        messages_collection = db.messages
        
        cursor = chats_collection.find(
            {"status": "pending", "operator_id": None, "is_active": True},
            {"_id": 1, "user_id": 1, "telegram_chat_id": 1, "title": 1, "created_at": 1, "status": 1}
        ).sort("created_at", 1)  
        
        pending_chats = await cursor.to_list(length=100)
        
        for chat in pending_chats:
            chat_id = chat.pop("_id")
            chat["chat_id"] = str(chat_id)
            
            first_message = await messages_collection.find_one(
                {"chat_id": chat_id, "flag": "user"},
                {"message": 1, "_id": 0},
                sort=[("date", 1)]
            )
            
            chat["first_message"] = first_message["message"] if first_message else ""
        
        logger.info(f"Найдено {len(pending_chats)} ожидающих чатов")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "count": len(pending_chats),
                "chats": pending_chats
            }
        )
    
    except Exception as e:
        logger.error(f"Ошибка при получении ожидающих чатов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/assigned")
async def get_assigned_chats(payload: dict = Depends(verify_token)):
    """
    Получает список чатов, назначенных текущему оператору.
    Доступно только авторизованным операторам.
    
    Args:
        payload: JWT токен оператора
    
    Returns:
        JSON со списком назначенных чатов с первым сообщением
    """
    try:
        # Получаем operator_id из токена (теперь там хранится MongoDB _id)
        operator_id = payload.get("operator_id")
        operator_email = payload.get("sub")
        
        if not operator_id and not operator_email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный токен"
            )
        
        db = get_database()
        chats_collection = db.chats
        messages_collection = db.messages
        
        # Ищем по operator_id (новые чаты) или по email (старые чаты для обратной совместимости)
        cursor = chats_collection.find(
            {
                "status": "assigned", 
                "operator_id": {"$in": [operator_id, operator_email]}, 
                "is_active": True
            },
            {"_id": 1, "user_id": 1, "telegram_chat_id": 1, "title": 1, "created_at": 1, "assigned_at": 1, "status": 1}
        ).sort("assigned_at", -1)  
        
        assigned_chats = await cursor.to_list(length=100)
        
        for chat in assigned_chats:
            chat_id = chat.pop("_id")
            chat["chat_id"] = str(chat_id)
            
            first_message = await messages_collection.find_one(
                {"chat_id": chat_id, "flag": "user"},
                {"message": 1, "_id": 0},
                sort=[("date", 1)]
            )
            
            chat["first_message"] = first_message["message"] if first_message else ""
        
        logger.info(f"Найдено {len(assigned_chats)} назначенных чатов для оператора {operator_id or operator_email}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "count": len(assigned_chats),
                "chats": assigned_chats
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении назначенных чатов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )
class CloseChatRequest(BaseModel):
    rating: int
    comment: str | None = None

class CloseChatOperatorRequest(BaseModel):
    comment: str | None = None

@router.post("/close/{user_id}")
async def close_chat_by_user(user_id: str,request_data: CloseChatRequest,):
    """
    Закрывает чат (завершает обращение) от имени пользователя.
    
    Args:
        user_id: ID пользователя
    
    Returns:
        JSON с результатом закрытия чата
    """
    try:
        db = get_database()
        collection = db.chats
        
        result = await collection.find_one_and_update(
            {"user_id": user_id, "is_active": True},
            {
                "$set": {
                    "is_active": False,
                    "status": "closed",
                    "closed_at": datetime.utcnow().isoformat()
                }
            },
            return_document=ReturnDocument.AFTER 
        )
        
        if result:
            await send_review_to_kafka(str(result["_id"]),int(request_data.rating),result["operator_id"],request_data.comment,"user")
            chat = await collection.find_one({"user_id": user_id})
            if chat:
                await invalidate_chat_cache(chat.get("telegram_chat_id"))
            
            logger.info(f"Чат пользователя {user_id} закрыт")
            get_messages_and_memorize(str(result["_id"], user_id))
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "success": True,
                    "chat_id":str(result["_id"]),
                    "message": "Чат успешно закрыт"
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Активный чат не найден"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при закрытии чата: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.post("/close-by-operator/{user_id}")
async def close_chat_by_operator(
    user_id: str,
    body: CloseChatOperatorRequest,
    payload: dict = Depends(verify_token)
):
    """
    Закрывает чат (завершает обращение) от имени оператора.
    Требует авторизацию оператора.
    
    Args:
        user_id: ID пользователя
        payload: JWT токен оператора
    
    Returns:
        JSON с результатом закрытия чата
    """
    try:
        db = get_database()
        collection = db.chats
        
        result = await collection.update_one(
            {"user_id": user_id, "is_active": True},
            {
                "$set": {
                    "is_active": False,
                    "status": "closed",
                    "closed_at": datetime.utcnow().isoformat()
                }

            },
            return_document=ReturnDocument.AFTER 
        )
        
        if result:
            logger.info(f"Чат пользователя {user_id} закрыт оператором")
            
            await send_review_to_kafka(str(result["_id"]),None,result["operator_id"],body.comment,"operator")
            get_messages_and_memorize(result["_id"],user_id)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "success": True,
                    "message": "Чат успешно закрыт"
                }
            )
            
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Активный чат не найден"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при закрытии чата: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


