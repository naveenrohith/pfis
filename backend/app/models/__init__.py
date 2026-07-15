"""
PFIS Models Package
Import all models here so SQLAlchemy's Base.metadata knows about them
when create_all() is called. Order matters for foreign key resolution.
"""

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.category import Category, Merchant
from app.models.email import GmailAccount, RawEmail
from app.models.summary import MonthlySummary
from app.models.sync import (
    BackgroundJob,
    Budget,
    ConnectorAuditEvent,
    Goal,
    OAuthState,
    ParseFailure,
    PipelineEvent,
    SyncRun,
    UserCorrection,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import DashboardPreference, RecommendationState

__all__ = [
    "User",
    "FinancialAccount",
    "AccountBalanceSnapshot",
    "Category",
    "Merchant",
    "RawEmail",
    "GmailAccount",
    "MonthlySummary",
    "Transaction",
    "SyncRun",
    "Budget",
    "UserCorrection",
    "ParseFailure",
    "PipelineEvent",
    "BackgroundJob",
    "Goal",
    "OAuthState",
    "ConnectorAuditEvent",
    "DashboardPreference",
    "RecommendationState",
]
