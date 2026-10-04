"""Async RabbitMQ layer for the OCR Worker.

Consumer for ocr.queue, producer for llm.queue. Uses a single robust
connection and channel, and relies on aio-pika's automatic reconnect.
"""

import json
from typing import Awaitable, Callable

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
)

from ocr_worker.config import get_settings
from ocr_worker.logging import get_logger

log = get_logger(__name__)

_connection: AbstractRobustConnection | None = None
_channel: AbstractRobustChannel | None = None


async def _get_connection() -> AbstractRobustConnection:
    """Return a process-wide robust AMQP connection (lazy)."""
    global _connection
    if _connection is None or _connection.is_closed:
        settings = get_settings()
        _connection = await aio_pika.connect_robust(
            settings.rabbitmq_url.get_secret_value(),
        )
        log.info("rabbitmq_connected")
    return _connection


async def _get_channel() -> AbstractRobustChannel:
    """Return a process-wide channel with prefetch configured."""
    global _channel
    if _channel is None or _channel.is_closed:
        settings = get_settings()
        connection = await _get_connection()
        _channel = await connection.channel()
        await _channel.set_qos(prefetch_count=settings.prefetch_count)
        log.info("rabbitmq_channel_opened", prefetch=settings.prefetch_count)
    return _channel


async def consume_ocr_queue(
    handler: Callable[[str], Awaitable[None]],
) -> None:
    """Consume ocr.queue forever.

    For each message:
      1. Parse the JSON payload, extract "document_id".
      2. Call handler(document_id).
      3. Ack on success, nack on failure (no requeue, so it goes to DLQ if
         configured; otherwise it's dropped).

    Args:
        handler: async function that processes one document_id.
    """
    settings = get_settings()
    channel = await _get_channel()

    # Declare both queues. OCR worker is the producer for llm.queue.
    ocr_queue = await channel.declare_queue(settings.ocr_queue, durable=True)
    await channel.declare_queue(settings.llm_queue, durable=True)

    log.info("rabbitmq_consuming", queue=settings.ocr_queue)

    async with ocr_queue.iterator() as iterator:
        async for message in iterator:
            await _handle_message(message, handler)


async def _handle_message(
    message: AbstractIncomingMessage,
    handler: Callable[[str], Awaitable[None]],
) -> None:
    """Process a single AMQP message: parse, dispatch, ack/nack."""
    try:
        payload = json.loads(message.body)
        document_id = payload.get("document_id")
        if not document_id:
            raise ValueError("missing 'document_id' in payload")
    except Exception as exc:
        log.warning("invalid_message", error=str(exc), body=message.body[:200])
        # Bad payload — drop it (nack without requeue).
        await message.nack(requeue=False)
        return

    try:
        await handler(document_id)
    except Exception as exc:
        log.error(
            "handler_failed",
            document_id=document_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        # Handler already logged details; nack without requeue.
        await message.nack(requeue=False)
        return

    await message.ack()


async def publish_llm_task(document_id: str) -> None:
    """Publish a document to llm.queue after successful OCR."""
    settings = get_settings()
    channel = await _get_channel()
    payload = {"document_id": document_id}
    message = Message(
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
    )
    await channel.default_exchange.publish(
        message,
        routing_key=settings.llm_queue,
    )
    log.info("rabbitmq_published", queue=settings.llm_queue, document_id=document_id)


async def check_rabbitmq() -> bool:
    """Health check: verify the connection is open and responsive."""
    try:
        connection = await _get_connection()
        if connection.is_closed:
            return False
        channel = await connection.channel()
        await channel.close()
        return True
    except Exception as exc:
        log.error("rabbitmq_health_check_failed", error=str(exc))
        return False


async def close_rabbitmq() -> None:
    """Close channel and connection gracefully."""
    global _connection, _channel
    if _channel is not None and not _channel.is_closed:
        await _channel.close()
        log.info("rabbitmq_channel_closed")
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
        log.info("rabbitmq_connection_closed")
    _connection = None
    _channel = None