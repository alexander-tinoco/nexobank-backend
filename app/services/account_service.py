"""Account service — business logic for bank account operations.

Rules (from CLAUDE.md)
----------------------
- No ``HTTPException`` here — raise domain exceptions only.
- No direct SQLAlchemy access — all DB operations go through the repository.
- Audit every sensitive operation via ``AuditLogRepository``.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountNotFoundError,
    UnauthorizedResourceError,
    UnsupportedCurrencyError,
)
from app.core.logging import get_logger
from app.models.account import Account, AccountType
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.account import SUPPORTED_CURRENCIES

logger = get_logger(__name__)


async def create_account(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    currency: str,
    account_type: AccountType,
) -> Account:
    """Create a new bank account for *user_id*.

    Steps
    -----
    1. Validate that *currency* is supported.
    2. Persist the account via the repository (generates a unique account number).
    3. Write an audit log entry.
    4. Return the created account.

    Raises
    ------
    UnsupportedCurrencyError
        When *currency* is not in the supported set.
    """
    normalised_currency = currency.upper()
    if normalised_currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(
            f"Currency '{currency}' is not supported. "
            f"Supported: {sorted(SUPPORTED_CURRENCIES)}"
        )

    account = await AccountRepository.create(
        db,
        user_id=user_id,
        currency=normalised_currency,
        type=account_type,
    )

    await AuditLogRepository.log(
        db,
        action="ACCOUNT_CREATED",
        user_id=user_id,
        entity_type="account",
        entity_id=account.id,
        metadata={"currency": normalised_currency, "type": account_type.value},
    )

    logger.info(
        "Account created",
        extra={"account_id": str(account.id), "user_id": str(user_id)},
    )
    return account


async def get_user_accounts(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[Account]:
    """Return all accounts belonging to *user_id*."""
    return await AccountRepository.get_by_user_id(db, user_id)


async def get_account(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> Account:
    """Return a single account, verifying ownership.

    Steps
    -----
    1. Fetch the account; raise ``AccountNotFoundError`` if missing.
    2. Verify the requesting user owns the account; raise
       ``UnauthorizedResourceError`` if not.
    3. Return the account.

    Raises
    ------
    AccountNotFoundError
        When no account with *account_id* exists.
    UnauthorizedResourceError
        When the account exists but belongs to a different user.
    """
    account = await AccountRepository.get_by_id(db, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account '{account_id}' not found.")

    if account.user_id != requesting_user_id:
        raise UnauthorizedResourceError(
            "You do not have permission to access this account."
        )

    return account


async def deposit_funds(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    amount: Decimal,
    description: str | None = None,
    ip_address: str | None = None,
) -> Transaction:
    """Credit *amount* to an account owned by *requesting_user_id*.

    Creates a ``deposit`` Transaction and updates the account balance atomically.
    Raises ``AccountNotFoundError`` or ``UnauthorizedResourceError`` on failure.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.account import Account  # noqa: PLC0415

    result = await db.execute(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    account = result.scalar_one_or_none()

    if account is None:
        raise AccountNotFoundError(f"Account '{account_id}' not found.")

    if account.user_id != requesting_user_id:
        raise UnauthorizedResourceError("You do not have permission to deposit into this account.")

    account.balance += amount

    tx = await TransactionRepository.create(
        db,
        account_id=account_id,
        type=TransactionType.deposit,
        amount=amount,
        status=TransactionStatus.completed,
        description=description or "External deposit",
    )

    await AuditLogRepository.log(
        db,
        action="DEPOSIT_COMPLETED",
        user_id=requesting_user_id,
        entity_type="transaction",
        entity_id=tx.id,
        ip_address=ip_address,
        metadata={"amount": str(amount), "account_id": str(account_id)},
    )

    logger.info(
        "Deposit completed",
        extra={"account_id": str(account_id), "amount": str(amount)},
    )
    return tx
