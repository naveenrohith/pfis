from app.schemas.dashboard import WorkspaceRecommendation
from app.services.recommendation_policy import (
    RecommendationFeedback,
    _apply_feedback,
)


def test_recommendation_feedback_freezes_on_negative_outcome_drift():
    feedback = RecommendationFeedback(completed_outcomes=4, helped=1, worse=3)
    assert feedback.learning_status == "drift"
    assert feedback.adjustment == -3

    recommendation = WorkspaceRecommendation(
        type="savings",
        severity="info",
        title="Reduce discretionary spend",
        description="Review one discretionary purchase.",
        action_label="Review",
        target="insights",
        priority=50,
        reason_codes=["savings"],
    )
    _apply_feedback(recommendation, feedback)
    assert recommendation.priority == 44
    assert "personalization_drift" in recommendation.reason_codes
    assert recommendation.evidence[-1]["label"] == "Personalization drift"


def test_recommendation_feedback_stays_unmeasured_below_minimum_sample():
    feedback = RecommendationFeedback(completed_outcomes=2, helped=2)
    assert feedback.learning_status == "insufficient_sample"
    assert feedback.adjustment == 0
