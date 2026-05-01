import aio_pika
from app.core.config import settings

connection = None
channel = None
exchange = None

EXCHANGE_NAME = "events.exchange"

async def connect_rabbitmq():
    global connection, channel, exchange
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )

async def close_rabbitmq():
    global connection
    if connection:
        await connection.close()

async def get_exchange():
    return exchange
