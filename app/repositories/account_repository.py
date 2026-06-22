"""Account repository — all database access for the Account model.

Rules
-----
- No business logic here; only query construction and result mapping.
- ``get_by_id_for_update`` acquires a row-level lock (``SELECT … FOR UPDATE``)
  to protect against concurrent balance modifications.
- ``account_number`` generation verifies uniqueness before returning.
"""

import random
import string
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus, AccountType


class AccountRepository:
    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        account_id: uuid.UUID,
    ) -> Account | None:
        """Return the account with the given primary key, or *None*."""
        result = await db.execute(
            select(Account).where(Account.id == account_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id_for_update(
        db: AsyncSession,
        account_id: uuid.UUID,
    ) -> Account | None:
        """Return the account locked for update (prevents concurrent balance edits).

        Used by the transactions / transfers service before modifying the balance.
        """
        result = await db.execute(
            select(Account)
            .where(Account.id == account_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user_id(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[Account]:
        """Return all accounts belonging to *user_id*."""
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_account_number(
        db: AsyncSession,
        account_number: str,
    ) -> Account | None:
        """Return the account matching *account_number*, or *None*."""
        result = await db.execute(
            select(Account).where(Account.account_number == account_number)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _generate_unique_account_number(
        db: AsyncSession,
        currency: str,
    ) -> str:
        """Generate a unique account number in the format ``{CURRENCY}{12 digits}``.

        Retries up to 10 times in the unlikely event of a collision.
        """
        prefix = currency.upper()
        for _ in range(10):
            digits = "".join(random.choices(string.digits, k=12))
            candidate = f"{prefix}{digits}"
            existing = await AccountRepository.get_by_account_number(db, candidate)
            if existing is None:
                return candidate
        # Statistically impossible but be explicit rather than looping forever.
        raise RuntimeError(
            "Could not generate a unique account number after 10 attempts."
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        currency: str,
        type: AccountType,
    ) -> Account:
        """Insert a new account and return the persisted instance."""
        account_number = await AccountRepository._generate_unique_account_number(
            db, currency
        )
        account = Account(
            user_id=user_id,
            account_number=account_number,
            currency=currency.upper(),
            type=type,
            balance=Decimal("0.00"),
            status=AccountStatus.active,
        )
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def update_balance(
        db: AsyncSession,
        account: Account,
        new_balance: Decimal,
    ) -> Account:
        """Persist *new_balance* on *account* and return the updated instance."""
        account.balance = new_balance
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def update_status(
        db: AsyncSession,
        account: Account,
        status: AccountStatus,
    ) -> Account:
        """Persist a new *status* on *account* and return the updated instance."""
        account.status = status
        db.add(account)
        await db.flush()
        return account
