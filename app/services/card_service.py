"""Card service — business logic for payment card operations.

Rules (from CLAUDE.md)
----------------------
- No ``HTTPException`` here — raise domain exceptions only.
- No direct SQLAlchemy access — all DB operations go through the repository.
- Audit every sensitive operation via ``AuditLogRepository``.
- Never store the full card number; only last 4 digits.
"""

import random
import string
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountFrozenError,
    AccountNotFoundError,
    CardNotFoundError,
    UnauthorizedResourceError,
)
from app.core.logging import get_logger
from app.models.account import AccountStatus
from app.models.card import Card, CardStatus, CardType
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.card_repository import CardRepository

logger = get_logger(__name__)

# Cards expire 3 years from the issue date (standard banking convention).
_CARD_VALIDITY_YEARS = 3


def _generate_last4() -> str:
    """Return a random 4-digit string — stands in for the real card last4."""
    return "".join(random.choices(string.digits, k=4))


def _compute_expiry(issue_date: date) -> date:
    """Return the last day of the month exactly *_CARD_VALIDITY_YEARS* years later."""
    import calendar

    expiry_year = issue_date.year + _CARD_VALIDITY_YEARS
    expiry_month = issue_date.month
    last_day = calendar.monthrange(expiry_year, expiry_month)[1]
    return date(expiry_year, expiry_month, last_day)


async def create_card(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    card_type: CardType,
) -> Card:
    """Issue a new card for *account_id*.

    Steps
    -----
    1. Verify the account exists and belongs to the requesting user.
    2. Reject if the account is frozen or closed.
    3. Generate last4 and expiry date.
    4. Persist via the repository.
    5. Write an audit log entry.

    Raises
    ------
    AccountNotFoundError
        When the account does not exist.
    UnauthorizedResourceError
        When the account exists but belongs to a different user.
    AccountFrozenError
        When the account is frozen or closed.
    """
    account = await AccountRepository.get_by_id(db, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account '{account_id}' not found.")

    if account.user_id != requesting_user_id:
        raise UnauthorizedResourceError(
            "You do not have permission to access this account."
        )

    if account.status in (AccountStatus.frozen, AccountStatus.closed):
        raise AccountFrozenError(
            f"Cannot issue a card for an account with status '{account.status.value}'."
        )

    last4 = _generate_last4()
    expires_at = _compute_expiry(date.today())

    card = await CardRepository.create(
        db,
        account_id=account_id,
        last4=last4,
        type=card_type,
        expires_at=expires_at,
    )

    await AuditLogRepository.log(
        db,
        action="CARD_CREATED",
        user_id=requesting_user_id,
        entity_type="card",
        entity_id=card.id,
        metadata={"last4": card.last4, "type": card_type.value},
    )

    logger.info(
        "Card created",
        extra={
            "card_id": str(card.id),
            "account_id": str(account_id),
            "user_id": str(requesting_user_id),
        },
    )
    return card


async def set_card_frozen(
    db: AsyncSession,
    *,
    card_id: uuid.UUID,
    frozen: bool,
    requesting_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> Card:
    """Freeze or unfreeze a card.

    Steps
    -----
    1. Fetch the card; raise ``CardNotFoundError`` if missing.
    2. Fetch the owning account and verify the requesting user owns it.
    3. Update the card status.
    4. Write an audit log entry.

    Raises
    ------
    CardNotFoundError
        When the card does not exist.
    UnauthorizedResourceError
        When the card's account belongs to a different user.
    """
    card = await CardRepository.get_by_id(db, card_id)
    if card is None:
        raise CardNotFoundError(f"Card '{card_id}' not found.")

    # Verify that the account linked to this card belongs to the requesting user.
    account = await AccountRepository.get_by_id(db, card.account_id)
    if account is None or account.user_id != requesting_user_id:
        raise UnauthorizedResourceError(
            "You do not have permission to modify this card."
        )

    new_status = CardStatus.frozen if frozen else CardStatus.active
    card = await CardRepository.update_status(db, card, new_status)

    audit_action = "CARD_FROZEN" if frozen else "CARD_UNFROZEN"
    await AuditLogRepository.log(
        db,
        action=audit_action,
        user_id=requesting_user_id,
        entity_type="card",
        entity_id=card.id,
        ip_address=ip_address,
        metadata={"last4": card.last4, "new_status": new_status.value},
    )

    logger.info(
        "Card status updated",
        extra={
            "card_id": str(card.id),
            "action": audit_action,
            "user_id": str(requesting_user_id),
        },
    )
    return card


async def get_account_cards(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> list[Card]:
    """Return all cards for *account_id*, verifying ownership.

    Raises
    ------
    AccountNotFoundError
        When the account does not exist.
    UnauthorizedResourceError
        When the account belongs to a different user.
    """
    account = await AccountRepository.get_by_id(db, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account '{account_id}' not found.")

    if account.user_id != requesting_user_id:
        raise UnauthorizedResourceError(
            "You do not have permission to access this account."
        )

    return await CardRepository.get_by_account_id(db, account_id)
