from agent.parsing import safe_parse_recommendation
from agent.schemas import ParseFailure, RecommendationResult


def test_valid_recommendation_parses():
    raw = '{"action": "WAIT", "reason": "valid promise", "confidence": 0.87, "expected_recovery": 38000, "recheck_in_days": 2}'
    result = safe_parse_recommendation(raw)
    assert isinstance(result, RecommendationResult)
    assert result.action.value == "WAIT"


def test_out_of_whitelist_action_is_rejected():
    """This is the core Failure E test: an LLM proposing something outside
    the action whitelist must never reach the policy engine as a live action."""
    raw = '{"action": "REFUND_CUSTOMER", "reason": "seems fair", "confidence": 0.9, "expected_recovery": 5000000}'
    result = safe_parse_recommendation(raw)
    assert isinstance(result, ParseFailure)
    assert "REFUND_CUSTOMER" in result.error or "action" in result.error.lower()


def test_malformed_json_is_rejected():
    raw = "{action: WAIT, this is not valid json"
    result = safe_parse_recommendation(raw)
    assert isinstance(result, ParseFailure)


def test_missing_required_field_is_rejected():
    raw = '{"action": "REMIND", "reason": "no confidence field"}'
    result = safe_parse_recommendation(raw)
    assert isinstance(result, ParseFailure)


def test_confidence_out_of_range_is_rejected():
    raw = '{"action": "WAIT", "reason": "overconfident", "confidence": 1.5, "expected_recovery": 100}'
    result = safe_parse_recommendation(raw)
    assert isinstance(result, ParseFailure)
