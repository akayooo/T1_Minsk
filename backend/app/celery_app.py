"""
Celery конфигурация для фоновой обработки OCR задач
"""

import os
import logging
from celery import Celery, signals
from celery.schedules import crontab

logger = logging.getLogger(__name__)


@signals.worker_process_init.connect
def init_worker(**kwargs):
    """
    Инициализация MongoDB подключения при запуске Celery worker процесса.
    Это необходимо т.к. каждый worker работает в отдельном процессе.
    """
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.database import mongodb
    
    try:
        mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
        mongodb.client = AsyncIOMotorClient(mongodb_url)
        
        # Проверяем подключение
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mongodb.client.admin.command('ping'))
        loop.close()
        
        logger.info(f"MongoDB подключен в Celery worker: {mongodb_url}")
    except Exception as e:
        logger.error(f"Ошибка подключения MongoDB в Celery worker: {e}")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/0")

# Создаем Celery приложение
celery_app = Celery(
    "t1_tasks",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=['app.tasks.ocr_tasks', 'app.tasks.notification_tasks', 'app.tasks.maintenance_tasks']
)

# Конфигурация Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Retry настройки
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Время жизни результатов
    result_expires=3600,  # 1 час
    
    # Лимиты
    task_time_limit=300,  # 5 минут максимум на задачу
    task_soft_time_limit=240,  # 4 минуты soft limit
    
    # Prefetch настройки для лучшей производительности
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    
    # Мониторинг
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Периодические задачи (если нужны)
celery_app.conf.beat_schedule = {
    'cleanup-old-tasks': {
        'task': 'app.tasks.maintenance_tasks.cleanup_old_results',
        'schedule': crontab(hour=3, minute=0),  # Каждую ночь в 3:00
    },
    'check-stuck-ocr-tasks': {
        'task': 'app.tasks.maintenance_tasks.check_stuck_tasks',
        'schedule': crontab(minute='*/30'),  # Каждые 30 минут
    },
}

logger.info(f"Celery сконфигурирован: broker={CELERY_BROKER_URL}")

