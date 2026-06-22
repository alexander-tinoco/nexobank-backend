"""Cards router — stub.

Endpoints (to be implemented by the cards agent):
- GET  /cards
- POST /cards
- GET  /cards/{card_id}
- POST /cards/{card_id}/freeze
- POST /cards/{card_id}/unfreeze
"""

from fastapi import APIRouter

router = APIRouter(prefix="/cards", tags=["cards"])
