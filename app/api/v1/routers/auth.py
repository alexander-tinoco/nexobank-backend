"""Authentication router — stub.

Endpoints (to be implemented by the auth agent):
- POST /auth/register
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
