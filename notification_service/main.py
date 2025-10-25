import asyncio
import json
import logging
import os
from typing import Dict, List

import uvicorn
from app.services.kafka import notification_consumer_task
from app.ws.routes import router
from fastapi import FastAPI
from contextlib import asynccontextmanager


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    kafka_task = asyncio.create_task(notification_consumer_task())
    yield
    kafka_task.cancel()
    try:
        await kafka_task
    except asyncio.CancelledError:
        logger.info("Задача Kafka-консьюмера успешно отменена.")

app = FastAPI(lifespan=lifespan)

app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)