"""Version registry for deterministic PFIS knowledge rules."""

from app.services.knowledge.contracts import RulesetReference

MERCHANT_RESOLUTION = RulesetReference("merchant-resolution", "pfis-merchant-1")
RECURRING_PATTERN = RulesetReference("recurring-pattern", "pfis-recurring-4")
CASH_FLOW = RulesetReference("cash-flow", "pfis-cash-flow-6")
CASH_FLOW_BACKTEST = RulesetReference("cash-flow-backtest", "pfis-cash-flow-backtest-2")
CASH_FLOW_OUTCOME = RulesetReference("cash-flow-outcome", "pfis-cash-flow-outcome-1")
MONTHLY_STABILITY = RulesetReference("monthly-stability", "pfis-stability-1")
DATA_CONFIDENCE = RulesetReference("data-confidence", "pfis-data-confidence-2")
TEMPORAL_EVENTS = RulesetReference("temporal-events", "pfis-temporal-events-1")
RECOMMENDATION_RANKING = RulesetReference("recommendation-ranking", "pfis-recommendation-2")
RECOMMENDATION_OUTCOME = RulesetReference("recommendation-outcome", "pfis-recommendation-outcome-1")
