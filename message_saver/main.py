import asyncio
from app.kafka_consumer import consume_kafka
from app.logger import logger

def main():
    logger.info("Strting...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(consume_kafka())
    except KeyboardInterrupt:
        logger.info('Shutting down consumer...')
    finally:
        loop.close()

if __name__ == '__main__':
    main()
