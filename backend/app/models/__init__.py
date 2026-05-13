"""
PFIS Models Package
Import all models here so SQLAlchemy's Base.metadata knows about them
when create_all() is called. Order matters for foreign key resolution.
"""

from app.models.user import User
from app.models.category import Category, Merchant
from app.models.email import RawEmail, GmailAccount
from app.models.transaction import Transaction
from app.models.sync import SyncRun, Budget, UserCorrection, ParseFailure, BackgroundJob

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
]
