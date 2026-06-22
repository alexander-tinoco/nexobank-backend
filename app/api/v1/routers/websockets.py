"""WebSocket endpoint para notificaciones en tiempo real."""

from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.logging import get_logger
from app.core.security import decode_access_token

logger = get_logger(__name__)

router = APIRouter(tags=["websockets"])


class ConnectionManager:
    """Gestiona conexiones WebSocket activas por user_id."""

    def __init__(self) -> None:
        # user_id -> list of websocket connections (un usuario puede tener varias sesiones)
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)
        logger.info("WebSocket connected", extra={"user_id": user_id})

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        conns = self._connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(user_id, None)
        logger.info("WebSocket disconnected", extra={"user_id": user_id})

    async def send_to_user(self, user_id: str, message: dict[str, Any]) -> None:
        """Envía un mensaje a todas las conexiones activas del usuario."""
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass  # conexión cerrada — se limpiará en disconnect


manager = ConnectionManager()


@router.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """
    WebSocket para notificaciones en tiempo real.

    Autenticación: JWT en query param ``?token=<access_token>``

    Eventos que el servidor envía:

    - ``{"type": "transaction", "data": {...}}``
    - ``{"type": "ping", "data": {}}``

    El cliente puede enviar:

    - ``{"type": "ping"}`` → servidor responde ``{"type": "pong"}``
    """
    subject = decode_access_token(token)
    if subject is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = subject
    await manager.connect(websocket, user_id)

    try:
        await websocket.send_json({"type": "connected", "data": {"user_id": user_id}})

        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "data": {}})

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as exc:
        logger.error("WebSocket error", extra={"user_id": user_id, "error": str(exc)})
        manager.disconnect(websocket, user_id)
