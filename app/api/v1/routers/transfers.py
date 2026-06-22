"""Transfers router — stub.

Endpoints (to be implemented by the transfers agent):
- POST /transfers  (requires Idempotency-Key header)
- GET  /transfers/{transfer_id}
"""

from fastapi import APIRouter

router = APIRouter(prefix="/transfers", tags=["transfers"])
