from agent.schemas import ParseFailure, RecommendationResult
from env.schemas import Action, ObservedEvidence
from policy.engine import apply_policy
from policy.schemas import MerchantPolicy


def make_observed(**overrides) -> ObservedEvidence:
    defaults = dict(
        case_id="t1",
        customer_id="cust_t1",
        amount=48000.0,
        days_past_due=10,
        historical_promise_keep_rate=0.78,
        on_time_payment_ratio=0.7,
        prior_intervention_count=1,
        prior_intervention_outcomes=["no_response"],
        recent_partial_payment=None,
        has_open_dispute=False,
        contact_note="Customer said they'll pay soon.",
        action_cost={"WAIT": 5.0, "REMIND": 25.0, "ESCALATE": 350.0, "STOP": 0.0},
    )
    defaults.update(overrides)
    return ObservedEvidence(**defaults)


def make_recommendation(**overrides) -> RecommendationResult:
    defaults = dict(action=Action.WAIT, reason="valid promise", confidence=0.85, expected_recovery=38000.0)
    defaults.update(overrides)
    return RecommendationResult(**defaults)


def test_normal_recommendation_passes_through_unchanged():
    obs = make_observed(prior_intervention_count=1)
    rec = make_recommendation(action=Action.WAIT, confidence=0.85)
    outcome = apply_policy(obs, rec)
    assert outcome.action == Action.WAIT
    assert not outcome.was_overridden


def test_max_attempts_forces_stop_even_with_confident_recommendation():
    obs = make_observed(prior_intervention_count=4)
    rec = make_recommendation(action=Action.ESCALATE, confidence=0.99)
    outcome = apply_policy(obs, rec, MerchantPolicy(max_attempts=4))
    assert outcome.action == Action.STOP
    assert outcome.was_overridden
    assert "max attempts" in outcome.reason


def test_parse_failure_forces_escalate_not_silent_drop():
    obs = make_observed()
    failure = ParseFailure(raw_output="garbage", error="invalid JSON")
    outcome = apply_policy(obs, failure)
    assert outcome.action == Action.ESCALATE
    assert outcome.was_overridden


def test_implausible_expected_recovery_is_rejected():
    obs = make_observed(amount=1000.0)
    rec = make_recommendation(action=Action.REMIND, expected_recovery=50_000_000.0, confidence=0.9)
    outcome = apply_policy(obs, rec)
    assert outcome.action == Action.ESCALATE
    assert outcome.was_overridden
    assert "implausible" in outcome.reason


def test_low_confidence_forces_escalate():
    obs = make_observed()
    rec = make_recommendation(action=Action.WAIT, confidence=0.2)
    outcome = apply_policy(obs, rec, MerchantPolicy(min_confidence_for_autonomous_action=0.55))
    assert outcome.action == Action.ESCALATE
    assert outcome.was_overridden


def test_low_confidence_escalate_recommendation_is_not_double_overridden():
    obs = make_observed()
    rec = make_recommendation(action=Action.ESCALATE, confidence=0.2)
    outcome = apply_policy(obs, rec, MerchantPolicy(min_confidence_for_autonomous_action=0.55))
    assert outcome.action == Action.ESCALATE
    assert not outcome.was_overridden


def test_attempt_limit_takes_precedence_over_parse_failure():
    obs = make_observed(prior_intervention_count=10)
    failure = ParseFailure(raw_output="garbage", error="invalid JSON")
    outcome = apply_policy(obs, failure, MerchantPolicy(max_attempts=4))
    assert outcome.action == Action.STOP
    assert "max attempts" in outcome.reason
