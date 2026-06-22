"""Users router — stub.

Endpoints (to be implemented by the users agent):
- GET  /users/me
- PATCH /users/me
- GET  /users/{user_id}  (admin)
"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])
