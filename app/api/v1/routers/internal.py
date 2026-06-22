"""
Endpoints internos para consumo por agentes de IA y servicios internos.

Autenticación: X-Internal-API-Key header (no JWT — son servicios de backend).
Estos endpoints NO deben ser expuestos públicamente.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, verify_internal_api_key
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


class UserContextResponse(BaseModel):
    """Contexto de un usuario para el Financial Coach y otros agentes de IA."""

    user_id: uuid.UUID
    full_name: str
    email: str
    status: str
    accounts: list[dict[str, Any]]  # lista simplificada de cuentas con balance
    total_balance_by_currency: dict[str, str]  # {"MXN": "15000.00", "USD": "500.00"}


class RiskEventRequest(BaseModel):
    """Evento de riesgo reportado por el motor de fraude."""

    user_id: uuid.UUID
    transaction_id: uuid.UUID | None = None
    event_type: str  # "suspicious_login", "unusual_transaction", "velocity_check"
    risk_score: float  # 0.0 - 1.0
    metadata: dict[str, Any] = {}


class RiskEventResponse(BaseModel):
    received: bool
    action_taken: str  # "flagged", "blocked", "monitoring"


@router.get("/users/{user_id}/context", response_model=UserContextResponse)
async def get_user_context(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UserContextResponse:
    """
    Retorna el contexto completo de un usuario para el Financial Coach.

    Incluye: datos personales, cuentas con balances, moneda total.

    TODO (mes 3): cuando los modelos User y Account estén integrados,
    reemplazar los imports tardíos con imports normales.
    """
    # Import tardío — los modelos estarán disponibles tras la integración de Fase 3
    from decimal import Decimal  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.account import Account  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        from app.core.exceptions import UserNotFoundError  # noqa: PLC0415

        raise UserNotFoundError(f"User {user_id} not found")

    accounts_result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    accounts = accounts_result.scalars().all()

    total_by_currency: dict[str, Decimal] = {}
    account_list: list[dict[str, Any]] = []
    for acc in accounts:
        account_list.append(
            {
                "id": str(acc.id),
                "account_number": acc.account_number,
                "currency": acc.currency,
                "balance": str(acc.balance),
                "status": acc.status,
                "type": acc.type,
            }
        )
        total_by_currency[acc.currency] = (
            total_by_currency.get(acc.currency, Decimal("0")) + acc.balance
        )

    return UserContextResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        status=user.status,
        accounts=account_list,
        total_balance_by_currency={k: str(v) for k, v in total_by_currency.items()},
    )


@router.post("/risk-events", response_model=RiskEventResponse)
async def receive_risk_event(
    body: RiskEventRequest,
    db: AsyncSession = Depends(get_db),
) -> RiskEventResponse:
    """
    Recibe eventos de riesgo del motor de fraude/scoring.

    Acciones posibles:

    - risk_score < 0.5: monitoring (solo log)
    - 0.5 <= risk_score < 0.8: flagged (log + audit)
    - risk_score >= 0.8: blocked (log + audit + TODO: suspender cuenta en mes 5)
    """
    from app.repositories.audit_log_repository import (
        AuditLogRepository,  # noqa: PLC0415
    )

    if body.risk_score >= 0.8:
        action = "blocked"
        await AuditLogRepository.log(
            db,
            action="HIGH_RISK_EVENT",
            user_id=body.user_id,
            entity_type="transaction" if body.transaction_id else "user",
            entity_id=body.transaction_id,
            metadata={
                "event_type": body.event_type,
                "risk_score": body.risk_score,
                **body.metadata,
            },
        )
        await db.commit()
    elif body.risk_score >= 0.5:
        action = "flagged"
        await AuditLogRepository.log(
            db,
            action="MEDIUM_RISK_EVENT",
            user_id=body.user_id,
            metadata={"event_type": body.event_type, "risk_score": body.risk_score},
        )
        await db.commit()
    else:
        action = "monitoring"

    logger.info(
        "Risk event processed",
        extra={
            "user_id": str(body.user_id),
            "event_type": body.event_type,
            "risk_score": body.risk_score,
            "action": action,
        },
    )

    return RiskEventResponse(received=True, action_taken=action)
