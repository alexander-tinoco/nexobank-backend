"""SQLAlchemy models package.

Import all concrete model classes here so that Alembic's ``env.py`` can
discover them by importing this module before generating migrations::

    from app.models import Base  # noqa: F401 — triggers model registration
"""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.transaction import Transaction

__all__ = ["AuditLog", "Base", "Transaction"]
