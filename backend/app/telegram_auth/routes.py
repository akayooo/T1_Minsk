from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging

from app.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telegram-auth", tags=["telegram-auth"])


class TelegramUserRegister(BaseModel):
    telegram_user_id: int
    telegram_chat_id: int
    first_name: str
    last_name: str
    username: Optional[str] = None


async def save_user_to_db(user_data: dict) -> bool:
    """
    Сохраняет пользователя в MongoDB.
    Использует upsert для обновления существующего пользователя или создания нового.
    """
    try:
        db = get_database()
        collection = db.users
        
        logger.info(f"Сохранение пользователя в БД: {user_data.get('telegram_user_id')}")
        
        result = await collection.update_one(
            {"telegram_user_id": user_data["telegram_user_id"]},
            {"$set": user_data},
            upsert=True
        )
        
        if result.upserted_id:
            logger.info(f"Создан новый пользователь с ID: {result.upserted_id}")
        elif result.modified_count > 0:
            logger.info(f"Обновлен существующий пользователь: {user_data['telegram_user_id']}")
        
        return result.acknowledged
    except Exception as e:
        logger.error(f"Ошибка при сохранении пользователя в БД: {e}")
        return False


async def get_user_from_db(telegram_user_id: int) -> Optional[dict]:
    """
    Получает пользователя из MongoDB по telegram_user_id.
    """
    try:
        db = get_database()
        collection = db.users
        
        user = await collection.find_one(
            {"telegram_user_id": telegram_user_id},
            {"_id": 0}  # Исключаем _id из результата
        )
        
        return user
    except Exception as e:
        logger.error(f"Ошибка при получении пользователя из БД: {e}")
        return None


@router.post("/register")
async def register_telegram_user(user: TelegramUserRegister):
    """
    Регистрирует пользователя через Telegram.
    
    Args:
        user: Данные пользователя из Telegram
    
    Returns:
        JSON с результатом регистрации
    """
    try:
        # Подготавливаем данные для сохранения
        user_data = {
            "telegram_user_id": user.telegram_user_id,
            "telegram_chat_id": user.telegram_chat_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "registered_at": datetime.utcnow().isoformat(),
            "is_active": True
        }
        
        # Сохраняем в БД
        success = await save_user_to_db(user_data)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Не удалось сохранить пользователя в базу данных"
            )
        
        logger.info(f"Пользователь {user.telegram_user_id} успешно зарегистрирован")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Пользователь успешно зарегистрирован",
                "user": {
                    "telegram_user_id": user.telegram_user_id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username
                }
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/user/{telegram_user_id}")
async def get_user(telegram_user_id: int):
    """
    Получает информацию о пользователе по Telegram ID.
    
    Args:
        telegram_user_id: Telegram ID пользователя
    
    Returns:
        JSON с данными пользователя
    """
    try:
        logger.info(f"Запрос пользователя с ID: {telegram_user_id}")
        
        user = await get_user_from_db(telegram_user_id)
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"Пользователь с telegram_user_id {telegram_user_id} не найден"
            )
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "user": user
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении пользователя: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

