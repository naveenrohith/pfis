"""
Rate limiter instance — shared across all route modules.

Separated from main.py to avoid circular imports when route files
need to apply @limiter.limit() decorators.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
