from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import asyncio
import time
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
import os

# Мониторинг и метрики
from prometheus_client import make_asgi_app, Counter, Histogram, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.message.routes import router as message_router
from app.telegram_auth.routes import router as telegram_auth_router
from app.auth.routes import router as auth_router
from app.chat.routes import router as chat_router
from app.ml.routes import router as ml_router
from app.database import connect_to_mongo, close_mongo_connection
from app.services.kafka import run_consumers
from app.cache import cache

logger = logging.getLogger(__name__)

# Prometheus метрики
REQUESTS_TOTAL = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration', ['method', 'endpoint'])
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Number of active connections')

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


async def create_kafka_topics():
    """Создает топики в Kafka при запуске приложения"""
    admin_client = AIOKafkaAdminClient(bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'))
    
    try:
        await admin_client.start()
        
        topics = [
            NewTopic(name='ticket_created', num_partitions=3, replication_factor=1),
            NewTopic(name='ocr_processed', num_partitions=3, replication_factor=1),
            NewTopic(name='kafka_dlq', num_partitions=1, replication_factor=1),  # Dead Letter Queue
            NewTopic(name='messages', num_partitions=3, replication_factor=1)  # Топик для сообщений
        ]
        
        try:
            await admin_client.create_topics(topics, validate_only=False)
            logger.info("Kafka топики созданы: ticket_created, ocr_processed, kafka_dlq")
        except Exception as e:
            if "already exists" in str(e).lower() or "TopicExistsException" in str(e):
                logger.info("Kafka топики уже существуют")
            else:
                logger.warning(f"Ошибка создания Kafka топиков: {e}")
    except Exception as e:
        logger.warning(f"Не удалось подключиться к Kafka: {e}")
    finally:
        await admin_client.close()


async def create_mongodb_indexes():
    """Создает индексы в MongoDB для оптимизации запросов"""
    from app.database import get_database
    
    try:
        db = get_database()
        
        # Индексы для коллекции messages
        await db.messages.create_index([("external_message_id", 1)], unique=True, background=True)
        await db.messages.create_index([("chat_id", 1)], background=True)
        await db.messages.create_index([("telegram_chat_id", 1)], background=True)
        await db.messages.create_index([("date", -1)], background=True)
        await db.messages.create_index([("chat_id", 1), ("date", -1)], background=True)
        
        # Индексы для коллекции chats
        await db.chats.create_index([("telegram_chat_id", 1), ("is_active", 1)], background=True)
        await db.chats.create_index([("user_id", 1), ("is_active", 1)], background=True)
        await db.chats.create_index([("operator_id", 1)], background=True)
        await db.chats.create_index([("status", 1), ("created_at", -1)], background=True)
        
        # Индексы для коллекции users
        await db.users.create_index([("telegram_user_id", 1)], unique=True, background=True)
        await db.users.create_index([("telegram_chat_id", 1)], background=True)
        
        # Индексы для коллекции operators
        await db.operators.create_index([("email", 1)], unique=True, background=True)
        
        logger.info("MongoDB индексы успешно созданы")
    except Exception as e:
        logger.error(f"Ошибка создания индексов MongoDB: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом: запуск и остановка фоновых служб.
    """
    # --- Код, выполняемый при старте приложения ---
    logger.info("Запуск служб...")
    
    # Подключение к MongoDB
    await connect_to_mongo()
    logger.info("MongoDB подключен")
    
    # Подключение к Redis
    await cache.connect()
    logger.info("Redis подключен")
    
    # Создание топиков Kafka
    await create_kafka_topics()
    logger.info("Kafka топики созданы")
    
    # Запуск Kafka консьюмеров в фоновой задаче
    consumer_task = asyncio.create_task(run_consumers())
    logger.info("Kafka консьюмеры запущены")
    
    # Создание индексов MongoDB
    await create_mongodb_indexes()
    logger.info("MongoDB индексы созданы")
    
    logger.info("Все службы запущены успешно!")
    
    yield  # В этот момент приложение готово принимать запросы
    
    # --- Код, выполняемый при остановке приложения ---
    logger.info("Остановка служб...")
    
    # Отмена задачи консьюмеров
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        logger.info("Задача консьюмеров успешно отменена")

    # Закрытие соединения с Redis
    await cache.close()
    logger.info("Redis подключение закрыто")

    # Закрытие соединения с БД
    await close_mongo_connection()
    logger.info("MongoDB подключение закрыто")
    
    logger.info("Все службы остановлены")


app = FastAPI(
    title="T1",
    description="API для сервиса техподдержки с AI-подсказками",
    version="1.0.0",
    lifespan=lifespan
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Настройка CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Только разрешенные origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware для метрик и логирования
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware для сбора метрик"""
    start_time = time.time()
    
    ACTIVE_CONNECTIONS.inc()
    
    try:
        response = await call_next(request)
        
        duration = time.time() - start_time
        
        # Записываем метрики
        REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        
        # Добавляем заголовки
        response.headers["X-Process-Time"] = str(duration)
        
        return response
    finally:
        ACTIVE_CONNECTIONS.dec()


# Инструментация Prometheus
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Подключаем роутеры
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(message_router)
app.include_router(telegram_auth_router)
app.include_router(ml_router)


@app.get("/")
async def root():
    """
    Корневой эндпоинт для проверки работы API
    """
    return {
        "message": "T1 Поддержка работает",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """
    Расширенная проверка здоровья сервиса
    """
    from app.database import get_database
    
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {}
    }
    
    # Проверка MongoDB
    try:
        db = get_database()
        await db.command('ping')
        health_status["services"]["mongodb"] = {"status": "healthy"}
    except Exception as e:
        health_status["services"]["mongodb"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "degraded"
    
    # Проверка Redis
    try:
        if await cache.exists("healthcheck"):
            await cache.delete("healthcheck")
        await cache.set("healthcheck", "ok", ttl=10)
        health_status["services"]["redis"] = {"status": "healthy"}
    except Exception as e:
        health_status["services"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "degraded"
    
    # Проверка Kafka (опционально)
    try:
        from aiokafka import AIOKafkaProducer
        producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_URL','localhost:9092'),
            request_timeout_ms=5000
        )
        await producer.start()
        await producer.stop()
        health_status["services"]["kafka"] = {"status": "healthy"}
    except Exception as e:
        health_status["services"]["kafka"] = {"status": "unhealthy", "error": str(e)}
        # Kafka не критичен для работы API
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/ready")
async def readiness_check():
    """
    Проверка готовности сервиса (для Kubernetes)
    """
    return {"status": "ready", "timestamp": time.time()}

