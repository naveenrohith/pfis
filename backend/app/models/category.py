"""
Category & Merchant Models
Category hierarchy + merchant normalization with alias support.
"""

import uuid
from sqlalchemy import String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Category(Base):
    """Transaction categories with parent-child hierarchy."""
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
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

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
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
