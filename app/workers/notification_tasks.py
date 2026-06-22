"""Celery tasks para notificaciones de eventos bancarios."""

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="nexobank.send_transaction_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_transaction_notification_task(
    self,  # type: ignore[misc]
    user_id: str,
    transaction_id: str,
    event_type: str,  # "transfer_sent", "transfer_received", "card_frozen"
    metadata: dict[str, Any],
) -> None:
    """
    Notifica al usuario sobre un evento de transacción.

    En producción esto enviaría: push notification (FCM/APNs), email, WebSocket.
    Por ahora: log del evento y simula envío.

    Reintenta hasta 3 veces con backoff exponencial si falla.
    """
    try:
        logger.info(
            "Sending transaction notification",
            extra={
                "user_id": user_id,
                "transaction_id": transaction_id,
                "event_type": event_type,
            },
        )
        # TODO (mes 3): Conectar con FCM/APNs real cuando llegue la capa móvil
        # TODO (mes 3): Enviar al WebSocket ConnectionManager si el usuario está conectado

    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)


@celery_app.task(name="nexobank.send_login_alert")
def send_login_alert_task(user_id: str, ip_address: str, timestamp: str) -> None:
    """Alerta al usuario de un nuevo login desde IP nueva."""
    logger.info(
        "Login alert triggered",
        extra={"user_id": user_id, "ip": ip_address},
    )
