"""
OCR задачи для обработки изображений и распознавания текста.
Используем Tesseract OCR для извлечения текста из изображений.

История:
1. Изначально планировалось использовать openbmb/MiniCPM-o-2_6, однако модель слишком большая, 
   наш сервер без GPU в связи с этим обработка занимает много времени.
2. В качестве альтернативы можем использовать microsoft/phi-4-multimodal-instruct из OpenRouter (vlm.py), 
   но это не подходит ТЗ.
"""

import os
import logging
from datetime import datetime
from celery import Task
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.celery_app import celery_app
from app.services.ocr import extract_text_from_url

import pymongo
import json
from confluent_kafka import Producer

logger = logging.getLogger(__name__)


class OCRTask(Task):
    """Базовый класс для OCR задач с повторными попытками"""
    
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  
    retry_jitter = True


@celery_app.task(
    bind=True,
    base=OCRTask,
    name='ocr_tasks.process_image',
    max_retries=3,
    default_retry_delay=60
)
def process_image_task(self, image_url: str, message_id: str):
    """
    Celery задача для обработки изображения через OCR.
    
    Args:
        self: Celery task instance
        image_url: URL изображения в S3
        message_id: External message ID для связи
    
    Returns:
        dict с результатом обработки
    """
    try:
        logger.info(f"Начало OCR обработки для сообщения {message_id}")
        logger.info(f"Image URL: {image_url}")
        
        extracted_text = analyze_image_with_retry(image_url)
        
        logger.info(f"OCR обработка завершена для {message_id}: {extracted_text[:100] if extracted_text else '(пустой текст)'}...")
        
        result = save_ocr_result(message_id, extracted_text)
        
        return {
            'status': 'success',
            'message_id': message_id,
            'extracted_text': extracted_text,
            'processed_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Ошибка OCR обработки для {message_id}: {e}")
        raise self.retry(exc=e, countdown=min(60 * (2 ** self.request.retries), 600))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True
)
def analyze_image_with_retry(image_url: str) -> str:
    """
    Вызов OCR с автоматическими повторными попытками.
    
    Args:
        image_url: URL изображения
    
    Returns:
        Распознанный текст из изображения
    """
    try:
        extracted_text = extract_text_from_url(image_url)
        
        if extracted_text and "ошибка" in extracted_text.lower():
            raise ValueError(f"OCR вернул ошибку: {extracted_text}")
        
        return extracted_text if extracted_text else ""
        
    except Exception as e:
        logger.error(f"Ошибка OCR: {e}")
        raise


def save_ocr_result(message_id: str, ocr_text: str) -> bool:
    """
    Сохраняет результат OCR в MongoDB и отправляет событие в Kafka.
    Использует синхронные библиотеки (PyMongo + confluent-kafka) для Celery prefork mode.
    
    Args:
        message_id: External message ID
        ocr_text: Распознанный текст
    
    Returns:
        True если успешно
    """
    
    import time
    
    try:
        # Обновляем сообщение в MongoDB (синхронно с PyMongo)
        mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
        database_name = os.getenv("DATABASE_NAME", "tech_support")
        
        mongo_client = pymongo.MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
        db = mongo_client[database_name]
        collection = db.messages
        
        max_retries = 5
        retry_delay = 0.5  # 500ms
        
        result = None
        for attempt in range(max_retries):
            result = collection.update_one(
                {"external_message_id": message_id},
                {
                    "$set": {
                        "ocr_text": ocr_text,
                        "ocr_processed_at": datetime.utcnow().isoformat()
                    }
                }
            )
            
            if result.modified_count > 0:
                break
            
            if attempt < max_retries - 1:
                logger.info(f"Сообщение {message_id} еще не в БД, попытка {attempt + 1}/{max_retries}, ждем {retry_delay}s...")
                time.sleep(retry_delay)
        
        mongo_client.close()
        
        if result and result.modified_count > 0:
            logger.info(f"OCR текст сохранен в MongoDB для {message_id}")
            logger.info(f"Первые 100 символов: {ocr_text[:100] if ocr_text else '(пустой текст)'}...")
        else:
            logger.warning(f"Сообщение {message_id} не найдено в MongoDB после {max_retries} попыток")
            return False
        
        # Отправляем событие в Kafka
        ocr_event = {
            "message_id": message_id,
            "ocr_text": ocr_text,
            "processed_at": datetime.utcnow().isoformat()
        }
        
        producer = Producer({
            'bootstrap.servers': os.getenv('KAFKA_URL', 'localhost:9092'),
            'compression.type': 'gzip',
            'max.in.flight.requests.per.connection': 5,
            'message.max.bytes': 10485760
        })
        
        # Отправляем сообщение
        producer.produce(
            'ocr_processed',
            value=json.dumps(ocr_event).encode('utf-8'),
            callback=lambda err, msg: logger.error(f"Kafka error: {err}") if err else None
        )
        
        # Ждем отправки всех сообщений
        producer.flush(timeout=10)
        
        logger.info(f"OCR событие отправлено в Kafka для {message_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка сохранения OCR результата: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


@celery_app.task(name='ocr_tasks.batch_process_images')
def batch_process_images_task(image_data_list: list):
    """
    Пакетная обработка нескольких изображений через OCR.
    
    Args:
        image_data_list: Список dict с image_url и message_id
    """
    results = []
    
    for image_data in image_data_list:
        try:
            # Создаем подзадачу для каждого изображения
            task = process_image_task.delay(
                image_data['image_url'],
                image_data['message_id']
            )
            results.append({
                'message_id': image_data['message_id'],
                'task_id': task.id,
                'status': 'queued'
            })
        except Exception as e:
            logger.error(f"Ошибка создания задачи для {image_data['message_id']}: {e}")
            results.append({
                'message_id': image_data['message_id'],
                'status': 'error',
                'error': str(e)
            })
    
    return results


@celery_app.task(name='ocr_tasks.get_task_status')
def get_task_status(task_id: str):
    """
    Получить статус задачи OCR обработки.
    
    Args:
        task_id: Celery task ID
    
    Returns:
        dict со статусом задачи
    """
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id, app=celery_app)
    
    return {
        'task_id': task_id,
        'status': result.status,
        'result': result.result if result.ready() else None,
        'traceback': result.traceback if result.failed() else None
    }

