"""SQLAlchemy models package.

Import all concrete model classes here so that Alembic's ``env.py`` can
discover them by importing this module before generating migrations::

    from app.models import Base  # noqa: F401 — triggers model registration
"""

from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.card import Card
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transaction
from app.models.user import User

__all__ = ["Account", "AuditLog", "Base", "Card", "RefreshToken", "Transaction", "User"]
