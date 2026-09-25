"""
PFIS Models Package
Import all models here so SQLAlchemy's Base.metadata knows about them
when create_all() is called. Order matters for foreign key resolution.
"""

from app.models.account import (
    AccountBalanceSnapshot,
    AccountBalanceSource,
    AccountLinkRule,
    FinancialAccount,
)
from app.models.anomaly import AnomalyAdjudication
from app.models.auth import AuthIdentity, AuthSession
from app.models.category import Category, Merchant, UserMerchantRule
from app.models.email import GmailAccount, RawEmail
from app.models.financial_change import FinancialChangeCursor, FinancialChangeEvent
from app.models.financial_position import (
    AccountBalanceReconciliation,
    CardCalendarEvent,
    CardPaymentIntent,
    CardPositionObservation,
    CardPreference,
    CashPlan,
    Commitment,
    CreditCardStatement,
    DepositAccountStatement,
    DepositStatementLine,
    DepositStatementLineReviewDecision,
    Liability,
    LiabilityScheduleItem,
    ReservePlan,
    StatementAnalysisReview,
    StatementImport,
    StatementLine,
    StatementLineMatch,
    StatementLineReviewDecision,
)
from app.models.forecast import (
    AccountBalanceForecastOutcome,
    AccountBalanceForecastSnapshot,
    CashFlowForecastOutcome,
    CashFlowForecastSnapshot,
)
from app.models.knowledge import SubscriptionReviewAction, TemporalEventDecision
from app.models.roadmap import (
    CardDispute,
    HealthChecklistItem,
    Household,
    HouseholdExpense,
    HouseholdMember,
    HouseholdSettlement,
    RoadmapBill,
)
from app.models.summary import MonthlySummary
from app.models.sync import (
    BackgroundJob,
    BalanceProviderAccountMapping,
    BalanceProviderConnection,
    Budget,
    ConnectorAuditEvent,
    Goal,
    OAuthState,
    ParseFailure,
    PipelineEvent,
    SyncRun,
    UserCorrection,
)
from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import Transaction, TransactionSplit
from app.models.user import User
from app.models.workspace import DashboardPreference, RecommendationOutcome, RecommendationState

__all__ = [
    "User",
    "AuthIdentity",
    "AuthSession",
    "FinancialAccount",
    "AccountBalanceSnapshot",
    "AccountBalanceSource",
    "AccountLinkRule",
    "AccountBalanceReconciliation",
    "CardPositionObservation",
    "AnomalyAdjudication",
    "Category",
    "Merchant",
    "UserMerchantRule",
    "RawEmail",
    "GmailAccount",
    "FinancialChangeCursor",
    "FinancialChangeEvent",
    "StatementImport",
    "StatementAnalysisReview",
    "CreditCardStatement",
    "DepositAccountStatement",
    "DepositStatementLine",
    "DepositStatementLineReviewDecision",
    "StatementLine",
    "StatementLineMatch",
    "StatementLineReviewDecision",
    "CardPreference",
    "CardPaymentIntent",
    "CardCalendarEvent",
    "Commitment",
    "CashPlan",
    "ReservePlan",
    "Liability",
    "LiabilityScheduleItem",
    "CashFlowForecastSnapshot",
    "CashFlowForecastOutcome",
    "AccountBalanceForecastSnapshot",
    "AccountBalanceForecastOutcome",
    "TemporalEventDecision",
    "SubscriptionReviewAction",
    "TemporalSourceSnapshot",
    "RoadmapBill",
    "HealthChecklistItem",
    "CardDispute",
    "Household",
    "HouseholdMember",
    "HouseholdExpense",
    "HouseholdSettlement",
    "MonthlySummary",
    "Transaction",
    "TransactionSplit",
    "SyncRun",
    "Budget",
    "UserCorrection",
    "ParseFailure",
    "PipelineEvent",
    "BackgroundJob",
    "BalanceProviderConnection",
    "BalanceProviderAccountMapping",
    "Goal",
    "OAuthState",
    "ConnectorAuditEvent",
    "DashboardPreference",
    "RecommendationState",
    "RecommendationOutcome",
]
