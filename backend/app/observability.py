"""Lightweight request-scoped observability helpers.

Provides a correlation id that is attached to every log record and surfaced on
responses via the ``X-Request-ID`` header. Kept dependency-free and minimal so
it is suitable for the local/single-user deployment profile.
"""

import logging
from contextvars import ContextVar

# Default "-" so log records emitted outside a request still format cleanly.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def install_request_id_logging() -> None:
    """Attach the request-id filter to all root logging handlers.

    Applied at the handler level so every record the handler emits — including
    those from third-party loggers — carries a ``request_id`` attribute and the
    log format never raises a missing-key error.
    """
    flt = RequestIdFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(flt)
