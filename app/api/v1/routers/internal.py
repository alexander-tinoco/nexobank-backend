"""Internal router — stub.

Endpoints (to be implemented by the internal agent):
- POST /internal/fraud-score
- POST /internal/freeze-account

All endpoints under this router require the X-Internal-API-Key header
(enforced via the verify_internal_api_key dependency from app.api.v1.deps).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/internal", tags=["internal"])
