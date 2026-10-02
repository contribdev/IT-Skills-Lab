"""Async RabbitMQ layer using aio-pika.

Provides a process-wide connection and channel, plus a helper to publish
messages to the OCR queue. Consumers are NOT defined here — they live in
the worker services.
"""

import json
from typing import Any

import aio_pika
from aio_pika import Channel, Connection, DeliveryMode, Message, Queue
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel

from api.config import get_settings
from api.logging import get_logger

log = get_logger(__name__)

_connection: AbstractRobustConnection | None = None
_channel: AbstractRobustChannel | None = None
_queue: Queue | None = None


async def get_connection() -> AbstractRobustConnection:
    """Return a process-wide robust AMQP connection (lazy)."""
    global _connection
    if _connection is None or _connection.is_closed:
        settings = get_settings()
        _connection = await aio_pika.connect_robust(
            settings.rabbitmq_url.get_secret_value(),
        )
        log.info("rabbitmq_connected")
    return _connection


async def get_channel() -> AbstractRobustChannel:
    """Return a process-wide channel (lazy)."""
    global _channel
    if _channel is None or _channel.is_closed:
        connection = await get_connection()
        _channel = await connection.channel()
        await _channel.set_qos(prefetch_count=1)
        log.info("rabbitmq_channel_opened")
    return _channel


async def get_ocr_queue() -> Queue:
    """Declare and return the OCR queue (idempotent)."""
    global _queue
    if _queue is None or _queue.channel.is_closed:
        settings = get_settings()
        channel = await get_channel()
        _queue = await channel.declare_queue(
            settings.ocr_queue,
            durable=True,
        )
        log.info("rabbitmq_queue_declared", queue=settings.ocr_queue)
    return _queue


async def publish_ocr_task(document_id: str) -> None:
    """Publish a document processing task to the OCR queue."""
    settings = get_settings()
    queue = await get_ocr_queue()
    payload = {"document_id": document_id}
    message = Message(
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
    )

    channel = await get_channel()
    await channel.default_exchange.publish(
        message,
        routing_key=settings.ocr_queue,
    )
    log.info("rabbitmq_published", queue=settings.ocr_queue, document_id=document_id)


async def check_rabbitmq() -> bool:
    """Health check: verify the connection is open and responsive."""
    try:
        connection = await get_connection()
        if connection.is_closed:
            return False
        # Open a throwaway channel to prove the broker responds.
        channel = await connection.channel()
        await channel.close()
        return True
    except Exception as exc:
        log.error("rabbitmq_health_check_failed", error=str(exc))
        return False


async def close_rabbitmq() -> None:
    """Close channel and connection. Called on application shutdown."""
    global _connection, _channel, _queue
    if _channel is not None and not _channel.is_closed:
        await _channel.close()
        log.info("rabbitmq_channel_closed")
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
        log.info("rabbitmq_connection_closed")
    _connection = None
    _channel = None
    _queue = None