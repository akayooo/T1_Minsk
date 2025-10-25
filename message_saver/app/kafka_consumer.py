import asyncio
import logging
from aiokafka import AIOKafkaConsumer
import json
from .config import KAFKA_URL
from .storage import save_message

logger = logging.getLogger('kafka_consumer')

async def consume_kafka():
    consumer = AIOKafkaConsumer(
        'ticket_created',
        'messages',  # Добавляем топик для первого сообщения
        bootstrap_servers=KAFKA_URL,
        group_id='backend-consumer-group',
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    await consumer.start()
    try:
        async for msg in consumer:
            message = msg.value
            logger.info(f'Received message from Kafka topic {msg.topic}: {message.get("message_id")}')
            saved_id = await save_message(message)
            if saved_id is None:
                logger.info('Message skipped due to idempotency')
            await consumer.commit()
    except Exception as e:
        logger.error(f'Error in Kafka consumer loop: {e}', exc_info=True)
        await consumer.commit()
    finally:
        await consumer.stop()
