"""Celery tasks para notificaciones de eventos bancarios.

Las notificaciones se envían publicando en canales Redis pub/sub.
El WebSocket handler (/ws/notifications) suscribe a esos canales
y reenvía los mensajes al cliente móvil en tiempo real.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

CHANNEL_PREFIX = "nexobank:notifications:user:"


@celery_app.task(  # type: ignore[misc]
    name="nexobank.send_transaction_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_transaction_notification_task(
    self: Any,
    sender_user_id: str,
    receiver_account_id: str,
    amount: str,
    currency: str,
    tx_id: str,
    description: str | None = None,
) -> None:
    """Publica notificaciones de transferencia en Redis para ambos usuarios.

    Notifica al remitente (transfer_sent) y al destinatario (transfer_received).
    El destinatario se busca en BD por account_id para obtener su user_id.
    """
    import asyncio  # noqa: PLC0415

    import redis  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415

    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

        # Notificar al remitente
        sender_payload = json.dumps({
            "type": "transfer_sent",
            "data": {
                "tx_id": tx_id,
                "amount": amount,
                "currency": currency,
                "description": description,
                "to_account_id": receiver_account_id,
            },
        })
        r.publish(f"{CHANNEL_PREFIX}{sender_user_id}", sender_payload)

        # Buscar user_id del destinatario y notificarlo
        async def _get_receiver_user_id() -> str | None:
            from sqlalchemy import select  # noqa: PLC0415

            from app.models.account import Account  # noqa: PLC0415
            from app.models.base import AsyncSessionLocal  # noqa: PLC0415

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Account.user_id).where(Account.id == receiver_account_id)
                )
                row = result.scalar_one_or_none()
                return str(row) if row else None

        receiver_user_id = asyncio.run(_get_receiver_user_id())

        if receiver_user_id and receiver_user_id != sender_user_id:
            receiver_payload = json.dumps({
                "type": "transfer_received",
                "data": {
                    "tx_id": tx_id,
                    "amount": amount,
                    "currency": currency,
                    "description": description,
                },
            })
            r.publish(f"{CHANNEL_PREFIX}{receiver_user_id}", receiver_payload)

        r.close()  # type: ignore[no-untyped-call]
        logger.info(
            "Transaction notifications published",
            extra={"tx_id": tx_id, "sender": sender_user_id},
        )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)


@celery_app.task(name="nexobank.send_login_alert")  # type: ignore[misc]
def send_login_alert_task(user_id: str, ip_address: str, timestamp: str) -> None:
    """Alerta al usuario de un nuevo login desde IP nueva."""
    import json  # noqa: PLC0415

    import redis  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415

    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        payload = json.dumps({
            "type": "login_alert",
            "data": {"ip_address": ip_address, "timestamp": timestamp},
        })
        r.publish(f"{CHANNEL_PREFIX}{user_id}", payload)
        r.close()  # type: ignore[no-untyped-call]
    except Exception:
        pass

    logger.info("Login alert triggered", extra={"user_id": user_id, "ip": ip_address})
