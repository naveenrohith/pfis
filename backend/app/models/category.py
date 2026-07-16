"""
Category & Merchant Models
Category hierarchy + merchant normalization with alias support.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def parse_merchant_aliases(aliases_json: str | None) -> list[str]:
    """Parse a merchant ``aliases`` JSON blob into a list of string aliases.

    Tolerates malformed/missing data and ignores non-string entries so callers
    do not have to repeat the same defensive ``json.loads`` handling.
    """
    try:
        aliases = json.loads(aliases_json) if aliases_json else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(aliases, list):
        return []
    return [alias for alias in aliases if isinstance(alias, str)]


class Category(Base):
    """Transaction categories with parent-child hierarchy."""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=True
    )
    icon: Mapped[str] = mapped_column(String(50), nullable=True)

    # Relationships
    transactions = relationship("Transaction", back_populates="category")
    budgets = relationship("Budget", back_populates="category")
    parent = relationship("Category", remote_side="Category.id", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class Merchant(Base):
    """Normalized merchant names with aliases for fuzzy matching."""

    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    normalized_name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    # JSON array of aliases: ["SWIGGY INDIA", "SWIGGY ONLINE", "SWIG"]
    aliases: Mapped[str] = mapped_column(Text, default="[]")
    category_default_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=True
    )

    # Relationships
    default_category = relationship("Category", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Merchant {self.normalized_name}>"


class UserMerchantRule(Base):
    """Exact, user-owned merchant normalization learned from explicit corrections."""

    __tablename__ = "user_merchant_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "descriptor_key", name="uq_user_merchant_rule_descriptor"),
        Index("ix_user_merchant_rules_user_name", "user_id", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    raw_descriptor: Mapped[str] = mapped_column(String(255), nullable=False)
    descriptor_key: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user_correction")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<UserMerchantRule user={self.user_id} key={self.descriptor_key}>"
