"""Version registry for deterministic PFIS knowledge rules."""

from app.services.knowledge.contracts import RulesetReference

MERCHANT_RESOLUTION = RulesetReference("merchant-resolution", "pfis-merchant-1")
RECURRING_PATTERN = RulesetReference("recurring-pattern", "pfis-recurring-2")
CASH_FLOW = RulesetReference("cash-flow", "pfis-cash-flow-3")
MONTHLY_STABILITY = RulesetReference("monthly-stability", "pfis-stability-1")
DATA_CONFIDENCE = RulesetReference("data-confidence", "pfis-data-confidence-1")
RECOMMENDATION_RANKING = RulesetReference("recommendation-ranking", "pfis-recommendation-2")
