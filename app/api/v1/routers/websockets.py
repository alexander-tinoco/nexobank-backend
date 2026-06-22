"""WebSocket endpoint para notificaciones en tiempo real.

Flujo:
1. Cliente conecta con JWT en query param ``?token=<access_token>``
2. Servidor autentica y acepta la conexión
3. Servidor suscribe al canal Redis ``nexobank:notifications:user:{user_id}``
4. Mensajes publicados en ese canal se reenvían al cliente en tiempo real
5. Cliente puede enviar ``{"type": "ping"}`` y recibe ``{"type": "pong"}``

Al desconectar, el servidor cancela la suscripción Redis y cierra el cliente.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import decode_access_token

logger = get_logger(__name__)

router = APIRouter(tags=["websockets"])

CHANNEL_PREFIX = "nexobank:notifications:user:"


def user_channel(user_id: str) -> str:
    return f"{CHANNEL_PREFIX}{user_id}"


@router.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """
    WebSocket para notificaciones en tiempo real.

    Autenticación: JWT en query param ``?token=<access_token>``

    Eventos que el servidor envía::

        {"type": "connected",         "data": {"user_id": "..."}}
        {"type": "transfer_sent",     "data": {"amount": "...", "tx_id": "..."}}
        {"type": "transfer_received", "data": {"amount": "...", "tx_id": "..."}}
        {"type": "pong",              "data": {}}

    El cliente puede enviar::

        {"type": "ping"}
    """
    import redis.asyncio as aioredis  # noqa: PLC0415

    subject = decode_access_token(token)
    if subject is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = subject
    await websocket.accept()
    await websocket.send_json({"type": "connected", "data": {"user_id": user_id}})
    logger.info("WebSocket connected", extra={"user_id": user_id})

    redis_client: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(user_channel(user_id))

    stop_event = asyncio.Event()

    async def redis_forwarder() -> None:
        """Lee mensajes de Redis y los reenvía al WebSocket."""
        try:
            async for message in pubsub.listen():
                if stop_event.is_set():
                    break
                if message["type"] == "message":
                    await websocket.send_text(message["data"])
        except Exception:
            pass

    async def client_handler() -> None:
        """Procesa mensajes entrantes del cliente (ping/pong)."""
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "data": {}})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    forwarder_task = asyncio.ensure_future(redis_forwarder())
    client_task = asyncio.ensure_future(client_handler())

    try:
        await asyncio.gather(forwarder_task, client_task)
    except Exception:
        pass
    finally:
        stop_event.set()
        forwarder_task.cancel()
        client_task.cancel()
        await pubsub.unsubscribe(user_channel(user_id))
        await redis_client.aclose()
        logger.info("WebSocket disconnected", extra={"user_id": user_id})
