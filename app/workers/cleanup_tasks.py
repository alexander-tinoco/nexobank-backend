"""Tareas periódicas de limpieza (Celery Beat)."""

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="nexobank.cleanup_expired_refresh_tokens")
def cleanup_expired_refresh_tokens_task() -> dict[str, Any]:
    """
    Borra refresh tokens expirados de la BD.

    Debe correr diariamente vía Celery Beat.
    El módulo auth (app.repositories.refresh_token_repository) tiene
    el método delete_expired() para esto.
    """
    import asyncio  # noqa: PLC0415

    async def _run() -> int:
        from app.models.base import AsyncSessionLocal  # noqa: PLC0415
        from app.repositories.refresh_token_repository import (  # noqa: PLC0415
            RefreshTokenRepository,
        )

        async with AsyncSessionLocal() as db:
            count = await RefreshTokenRepository.delete_expired(db)
            await db.commit()
            return count

    count = asyncio.run(_run())
    logger.info("Cleaned up expired refresh tokens", extra={"deleted_count": count})
    return {"deleted_count": count}


@celery_app.task(name="nexobank.generate_monthly_statement")
def generate_monthly_statement_task(
    user_id: str, account_id: str, year: int, month: int
) -> dict[str, Any]:
    """
    Genera el estado de cuenta mensual para un usuario.

    TODO (mes 6): implementar generación real de PDF/CSV para analytics.
    """
    logger.info(
        "Generating monthly statement",
        extra={
            "user_id": user_id,
            "account_id": account_id,
            "year": year,
            "month": month,
        },
    )
    return {"status": "queued", "user_id": user_id, "period": f"{year}-{month:02d}"}
