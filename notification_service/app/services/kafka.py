
import json
import logging
import os

from aiokafka import AIOKafkaConsumer


from app.services.wsmanager import ws_manager

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

KAFKA_URL = os.getenv('KAFKA_URL', 'localhost:9092') 

async def notification_consumer_task():
    """Слушает Kafka и коммитит offset только при успешной доставке оператору."""
    consumer = AIOKafkaConsumer(
        'websocket_notifications',
        bootstrap_servers=KAFKA_URL,
        group_id='websocket-notifier-group-v2',
        auto_offset_reset='earliest',
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        enable_auto_commit=False
    )
    
    await consumer.start()
    logger.info(f"Сервис уведомлений запущен.")
    
    try:
        async for msg in consumer:
            logger.info(f"Получено событие из Kafka, offset: {msg.offset}")
            try:
                event = msg.value
                chat_id = event.get("chat_id")
                
                if not chat_id:
                    logger.warning(f"Событие без chat_id, offset {msg.offset} НЕ будет подтвержден.")
                    continue
                is_delivered = await ws_manager.send_message_to_operator(chat_id, event)
                
                if is_delivered:
                    logger.info(f"Уведомление успешно доставлено оператору в чате {chat_id}.")
                    await consumer.commit() 
                    logger.info(f"Offset {msg.offset} успешно подтвержден.")
                else:
                    logger.warning(f"Оператор не в сети в чате {chat_id}. Offset {msg.offset} НЕ будет подтвержден. Попытка будет повторена.")

            except Exception as e:
                logger.error(f"Критическая ошибка обработки. Offset {msg.offset} НЕ будет подтвержден. Ошибка: {e}", exc_info=True)

    finally:
        await consumer.stop()
        logger.info("Сервис уведомлений остановлен.")