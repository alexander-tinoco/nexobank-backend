"""Placeholder para evaluación de riesgo de transacciones.

Este task se conectará al motor de fraude/scoring en el mes 5-6.
Por ahora registra el evento y aprueba todo (sin bloqueos).
"""

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="nexobank.evaluate_transaction_risk",
    bind=True,
    max_retries=2,
)
def evaluate_transaction_risk_task(
    self,  # type: ignore[misc]
    transaction_id: str,
    user_id: str,
    amount: str,  # Decimal serializado como str
    from_account_id: str,
    to_account_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Evalúa el riesgo de una transacción.

    Siempre recibe IDs (strings), nunca objetos ORM — seguro para serialización.

    Retorna: {"risk_score": float, "approved": bool, "flags": list[str]}

    TODO (mes 5-6): implementar modelo real de scoring/fraude.
    """
    logger.info(
        "Evaluating transaction risk",
        extra={
            "transaction_id": transaction_id,
            "amount": amount,
            "user_id": user_id,
        },
    )
    # Placeholder — aprueba todo por ahora
    return {"risk_score": 0.0, "approved": True, "flags": []}
