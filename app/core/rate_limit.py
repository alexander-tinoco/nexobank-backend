"""Shared slowapi Limiter instance.

Creating the Limiter here (rather than in ``app.main``) avoids circular imports
when routers need to decorate endpoints with ``@limiter.limit(...)`` at import
time, before ``app.main`` is fully loaded.

Both ``app/main.py`` and any router can import from this module::

    from app.core.rate_limit import limiter
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter: Limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
