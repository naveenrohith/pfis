"""Common, serializable contracts for explainable financial knowledge."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class SignalStatus(StrEnum):
    OBSERVED = "observed"
    CALCULATED = "calculated"
    FORECAST = "forecast"
    RECOMMENDATION = "recommendation"


class DataSufficiency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Aggregate evidence safe to expose without leaking raw source records."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class RulesetReference:
    key: str
    version: str


@dataclass(frozen=True, slots=True)
class SignalEnvelope:
    """Standard metadata carried by calculated and forecast intelligence."""

    kind: str
    status: SignalStatus
    value: Any
    confidence: float
    data_sufficiency: DataSufficiency
    sample_size: int
    ruleset: RulesetReference
    evidence: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    data_through: date | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
