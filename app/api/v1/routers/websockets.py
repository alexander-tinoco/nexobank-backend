"""WebSocket router — stub.

Endpoints (to be implemented by the realtime agent):
- WS /ws/notifications
"""

from fastapi import APIRouter

router = APIRouter(prefix="/ws", tags=["websockets"])
