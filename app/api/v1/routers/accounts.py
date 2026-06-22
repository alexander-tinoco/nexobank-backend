"""Accounts router — stub.

Endpoints (to be implemented by the accounts agent):
- GET  /accounts
- POST /accounts
- GET  /accounts/{account_id}
- GET  /accounts/{account_id}/balance
"""

from fastapi import APIRouter

router = APIRouter(prefix="/accounts", tags=["accounts"])
