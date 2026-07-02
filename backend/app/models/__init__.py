"""
PFIS Models Package
Import all models here so SQLAlchemy's Base.metadata knows about them
when create_all() is called. Order matters for foreign key resolution.
"""

from app.models.category import Category, Merchant
from app.models.email import GmailAccount, RawEmail
from app.models.sync import (
    BackgroundJob,
    Budget,
    ConnectorAuditEvent,
    Goal,
    OAuthState,
    ParseFailure,
    SyncRun,
    UserCorrection,
)
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "User",
    "Category",
    "Merchant",
    "RawEmail",
    "GmailAccount",
    "Transaction",
    "SyncRun",
    "Budget",
    "UserCorrection",
    "ParseFailure",
    "BackgroundJob",
    "Goal",
    "OAuthState",
    "ConnectorAuditEvent",
]
