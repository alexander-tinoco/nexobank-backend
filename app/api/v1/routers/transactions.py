"""Transactions router — stub.

Endpoints (to be implemented by the transactions agent):
- GET /transactions
- GET /transactions/{transaction_id}
"""

from fastapi import APIRouter

router = APIRouter(prefix="/transactions", tags=["transactions"])
