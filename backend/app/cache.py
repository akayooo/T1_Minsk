"""
Redis кэширование для улучшения производительности
"""

import os
import json
import logging
from typing import Optional, Any
from redis import asyncio as aioredis
from functools import wraps

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL", "3600"))  # 1 час по умолчанию


class RedisCache:
    """Singleton класс для работы с Redis кэшем"""
    
    _instance = None
    _redis: Optional[aioredis.Redis] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self):
        """Подключение к Redis"""
        try:
            self._redis = await aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50
            )
            await self._redis.ping()
            logger.info(f"Подключение к Redis успешно: {REDIS_URL}")
        except Exception as e:
            logger.error(f"Ошибка подключения к Redis: {e}")
            self._redis = None
    
    async def close(self):
        """Закрытие подключения к Redis"""
        if self._redis:
            await self._redis.close()
            logger.info("Redis подключение закрыто")
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кэша"""
        if not self._redis:
            return None
        
        try:
            value = await self._redis.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Ошибка чтения из Redis: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Установить значение в кэш"""
        if not self._redis:
            return False
        
        try:
            ttl = ttl or CACHE_TTL
            serialized = json.dumps(value, default=str)
            await self._redis.setex(key, ttl, serialized)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Ошибка записи в Redis: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Удалить значение из кэша"""
        if not self._redis:
            return False
        
        try:
            await self._redis.delete(key)
            logger.debug(f"🗑️ Cache DELETE: {key}")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления из Redis: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Проверить существование ключа"""
        if not self._redis:
            return False
        
        try:
            return await self._redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Ошибка проверки существования ключа: {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Инкремент счетчика (для rate limiting)"""
        if not self._redis:
            return None
        
        try:
            return await self._redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Ошибка инкремента: {e}")
            return None
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Установить TTL для ключа"""
        if not self._redis:
            return False
        
        try:
            await self._redis.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Ошибка установки TTL: {e}")
            return False


# Singleton instance
cache = RedisCache()


def cached(ttl: Optional[int] = None, key_prefix: str = ""):
    """
    Декоратор для кэширования результатов функций
    
    Usage:
        @cached(ttl=600, key_prefix="user")
        async def get_user(user_id: int):
            return await db.users.find_one({"id": user_id})
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Формируем ключ кэша
            cache_key = f"{key_prefix}:{func.__name__}:{args}:{kwargs}"
            
            # Проверяем кэш
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Вызываем функцию
            result = await func(*args, **kwargs)
            
            # Сохраняем в кэш
            if result is not None:
                await cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


async def get_active_chat_cached(telegram_chat_id: int) -> Optional[str]:
    """
    Получить ID активного чата с кэшированием
    
    Args:
        telegram_chat_id: Telegram chat ID
    
    Returns:
        chat_id (ObjectId в виде строки) или None
    """
    cache_key = f"active_chat:{telegram_chat_id}"
    
    # Проверяем кэш
    cached_chat_id = await cache.get(cache_key)
    if cached_chat_id:
        return cached_chat_id
    
    # Если нет в кэше - загружаем из БД
    from app.database import get_database
    
    try:
        db = get_database()
        collection = db.chats
        
        chat = await collection.find_one(
            {"telegram_chat_id": telegram_chat_id, "is_active": True}
        )
        
        if chat:
            chat_id = str(chat.get("_id"))
            # Кэшируем на 1 час
            await cache.set(cache_key, chat_id, ttl=3600)
            return chat_id
        
        return None
    except Exception as e:
        logger.error(f"Ошибка получения активного чата: {e}")
        return None


async def invalidate_chat_cache(telegram_chat_id: int):
    """
    Инвалидация кэша чата (при закрытии/создании)
    """
    cache_key = f"active_chat:{telegram_chat_id}"
    await cache.delete(cache_key)
    logger.info(f"Кэш инвалидирован для чата {telegram_chat_id}")

