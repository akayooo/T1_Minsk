from fastapi import APIRouter, HTTPException, Depends, status, Query 
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging
import httpx
import os
import requests
from bson import ObjectId

from app.database import get_database
from app.auth.routes import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml:8004/assist")

async def get_or_create_ai_response(db, message_id: str, new_response_data: dict = None):
    """
    Ищет существующий ответ AI по message_id или создает новый.
    - Если new_response_data is None: только ищет.
    - Если new_response_data не None: ищет, и если не находит, создает новую запись.
    """
    collection = db.ai_responses
    
    # Пытаемся найти существующий ответ
    cached_response = await collection.find_one({"message_id": message_id})
    if cached_response:
        logger.info(f"Найден кешированный ответ для message_id: {message_id}")
        return cached_response.get("ai_response")

    # Если кеш пуст и переданы данные для создания новой записи
    if new_response_data:
        try:
            document = {
                "message_id": message_id,
                "ai_response": new_response_data,
                "timestamp": datetime.utcnow()
            }
            await collection.insert_one(document)
            logger.info(f"Новый ответ AI для message_id {message_id} сохранен.")
            return new_response_data
        except Exception as e:
            logger.error(f"Не удалось сохранить ответ AI для message_id {message_id}: {e}", exc_info=True)
            # Возвращаем ответ даже в случае ошибки сохранения
            return new_response_data
            
    return None

@router.get("/assist")
async def generate_hints_for_operator_get(
    message_id: str = Query(..., description="ID сообщения, для которого нужны подсказки"),
    current_user: dict = Depends(verify_token)
):
    """
    Генерирует AI-подсказки для оператора на основе конкретного сообщения (GET-запрос).
    
    Принимает `message_id` как query-параметр.
    """
    try:
        db = get_database()

        cached_response = await get_or_create_ai_response(db, message_id)
        if cached_response:
            return cached_response

        target_message = None
        try:
            message_obj_id = ObjectId(message_id)
            target_message = await db.messages.find_one({"_id": message_obj_id})
        except Exception:
            # Если не удалось преобразовать в ObjectId, пробуем искать по external_message_id
            logger.info(f"Не удалось преобразовать в ObjectId, ищем по external_message_id: {message_id}")
            pass
            
        # Если не нашли по _id, ищем по external_message_id (UUID от Kafka)
        if not target_message:
            target_message = await db.messages.find_one({"external_message_id": message_id})
        
        if not target_message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Сообщение с ID {message_id} не найдено"
            )
            
        chat_id = target_message.get("chat_id")
        if not chat_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У сообщения отсутствует chat_id, невозможно собрать контекст"
            )

        # Улучшение: получаем историю сообщений, предшествующих текущему,
        # чтобы контекст был релевантным.
        target_message_date = target_message.get("date")
        history_cursor = db.messages.find(
            {
                "chat_id": chat_id,
                # Исключаем текущее и все последующие сообщения из истории
                "date": {"$lt": target_message_date}
            },
            {"_id": 0, "message": 1, "flag": 1}
        ).sort("date", -1).limit(10) # Берем 10 последних
        
        history_messages = await history_cursor.to_list(length=10)
        history_messages.reverse() # Восстанавливаем хронологический порядок

        # Формируем payload в требуемом формате
        # Маппинг ролей: "user" -> "client", "operator" -> "operator"
        payload = {
            "user_request": target_message.get("message", ""),
            "last_messages": [
                {
                    "role": "client" if msg.get("flag") == "user" else "operator",
                    "content": msg.get("message", "")
                }
                for msg in history_messages
            ]
        }
        
        logger.info(f"Запрос подсказок для сообщения {message_id} в чате {chat_id}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                ML_SERVICE_URL+"/assist",
                json=payload,
                timeout=200
            )
            
        if response.status_code != 200:
            logger.error(f"ML-сервис вернул ошибку: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Ошибка при обращении к ML-сервису: {response.text}"
            )
        ai_response = response.json()
        
        await get_or_create_ai_response(db, message_id, ai_response)
        
        return ai_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Критическая ошибка при генерации подсказок: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при генерации подсказок"
        )

def classify_question(
    question: str, 
) :
 
    url = f"{ML_SERVICE_URL}/classifier"
    payload = {"question": question}

    try:
        response = requests.post(url, json=payload, timeout=10) 

        response.raise_for_status()

        data = response.json()
        print(f"[Успех! Категория:] '{data['main_category']}',{data['subcategory']}")
        return data['main_category'] , data['subcategory']

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            print(f"Ошибка 400 Bad Request: Неверные входные данные.{e.response.text}")
        else:
            print(f"Ошибка HTTP: {e}")
        return None, None
    except requests.exceptions.ConnectionError as e:
        print(f"Ошибка подключения: не удалось подключиться к {url}. ")
        return None, None
    except requests.exceptions.Timeout:
        print(f"Ошибка: Запрос к{url} превысил время ожидания.")
        return None, None
    except Exception as e:
        print(f"Произошла непредвиденная ошибка: {e}")
        return None, None
    
def get_messages_and_memorize(
    chat_id_str: str,
    user_id: str
):

    client = None
    try:
        db = get_database()
        chat_id_obj = ObjectId(chat_id_str)
        collection = db.messages
        messages_cursor = collection.find(
            {"chat_id": chat_id_obj}
        ).sort("date", 1)
        
        dialogue = []
        for msg in messages_cursor:
            role = msg.get('flag', 'client')
            if role != 'operator':
                role = 'client'

            dialogue.append({
                "role": role,
                "content": msg.get("message", "") 
            })

        if not dialogue:
            print(f"Для чата {chat_id_str} не найдено сообщений. Отправка отменена.")
            return None
        payload = {
            "user_id": user_id,
            "dialogue": dialogue
        }

        print(f"Отправка {len(dialogue)} сообщений...")
        response = requests.post(ML_SERVICE_URL + "/memorize", json=payload)
        response.raise_for_status()

        print("Запрос на /memorize успешно выполнен!")
        return response.json()

    except Exception as e:
        print(f"Произошла ошибка в процессе получения и отправки сообщений: {e}")
        return None
    
    finally:
        if client:
            client.close()

