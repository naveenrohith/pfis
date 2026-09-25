"""Score the reviewed typed guidance query-plan fixture."""

from __future__ import annotations

from app.services.guidance.query_planner import GuidanceQueryRefusal, plan_guidance_query

from tests.pytest.guidance_query_eval_cases import (
    GUIDANCE_QUERY_EVAL_CASES,
    GUIDANCE_QUERY_EVAL_VERSION,
)


def test_guidance_query_eval_fixture_scores_critical_and_unsupported_cases():
    assert GUIDANCE_QUERY_EVAL_VERSION == "guidance-query-eval-v1"

    critical_cases = [case for case in GUIDANCE_QUERY_EVAL_CASES if case.get("critical")]
    unsupported_cases = [case for case in GUIDANCE_QUERY_EVAL_CASES if case.get("unsupported")]

    critical_correct = 0
    for case in critical_cases:
        result = plan_guidance_query(case["query"])
        assert not isinstance(result, GuidanceQueryRefusal), case["id"]
        assert result.intent == case["expected_intent"], case["id"]
        assert result.confidence >= 0.58, case["id"]
        assert result.read_models, case["id"]
        assert {slot.value for slot in result.required_slots}.issubset(result.slots), case["id"]
        critical_correct += 1

    unsupported_refusals = 0
    for case in unsupported_cases:
        result = plan_guidance_query(case["query"])
        if isinstance(result, GuidanceQueryRefusal):
            unsupported_refusals += 1

    assert critical_correct == len(critical_cases)
    assert unsupported_refusals / len(unsupported_cases) >= 0.9
