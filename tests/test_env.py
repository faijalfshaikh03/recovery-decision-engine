from env.baselines import always_pursue, fixed_cadence, simple_heuristic
from env.generator import generate_batch
from env.metrics import evaluate_policy
from env.oracle import oracle_decide, p_recovery, true_ev_of
from env.schemas import Action, CaseCategory, InterventionHistory, PromiseOutcome, SignalQuality, ValueBucket


def test_generate_batch_produces_valid_cases():
    cases = generate_batch(50, seed=1)
    assert len(cases) == 50
    for c in cases:
        assert c.observed.amount > 0
        assert 0 <= c.observed.days_past_due <= 60
        assert c.observed.contact_note


def test_generate_batch_covers_taxonomy():
    n = len(list(SignalQuality)) * len(list(ValueBucket)) * len(list(PromiseOutcome)) * len(list(InterventionHistory))
    cases = generate_batch(n, seed=2)
    seen = {
        (c.category.signal_quality, c.category.value_bucket, c.category.promise_outcome, c.category.intervention_history)
        for c in cases
    }
    assert len(seen) == n


def test_stop_has_zero_recovery_probability():
    cases = generate_batch(20, seed=3)
    for c in cases:
        assert p_recovery(Action.STOP, c.hidden) == 0.0


def test_oracle_picks_from_whitelist():
    cases = generate_batch(30, seed=4)
    for c in cases:
        decision = oracle_decide(c)
        assert decision.action in list(Action)


def test_oracle_never_loses_to_itself():
    """Oracle's own action must have the best (or tied-best) true EV by construction."""
    cases = generate_batch(30, seed=5)
    for c in cases:
        oracle_action = oracle_decide(c).action
        oracle_ev = true_ev_of(c, oracle_action)
        for a in list(Action):
            assert true_ev_of(c, a) <= oracle_ev + 1e-9


def test_kept_promise_favors_wait_in_expectation():
    category = CaseCategory(
        signal_quality=SignalQuality.CLEAN,
        value_bucket=ValueBucket.HIGH,
        promise_outcome=PromiseOutcome.KEPT,
        intervention_history=InterventionHistory.FIRST_CONTACT,
    )
    from env.generator import _generate_one
    import random

    rng = random.Random(0)
    case = _generate_one(rng, "test_kept", category)
    assert case.hidden.promise_will_be_kept is True
    assert p_recovery(Action.WAIT, case.hidden) > p_recovery(Action.STOP, case.hidden)


def test_baselines_return_valid_actions():
    cases = generate_batch(10, seed=6)
    for c in cases:
        for fn in (always_pursue, fixed_cadence, simple_heuristic):
            decision = fn(c)
            assert decision.action in list(Action)


def test_evaluate_policy_produces_summary():
    cases = generate_batch(40, seed=7)
    result = evaluate_policy(cases, always_pursue)
    assert result["summary"]["n_cases"] == 40
    assert "mean_regret" in result["summary"]
    assert "oracle_agreement_rate" in result["summary"]


def test_stop_is_reachable_at_a_real_but_low_rate():
    """Regression guard: STOP must be economically reachable (the spec's
    'sometimes the correct answer is do nothing' claim), but should stay rare
    - most receivables genuinely are worth one cheap attempt. If this drifts
    to 0%, the economics have regressed to WAIT/REMIND trivially dominating
    again; if it drifts too high, the model has become unrealistically
    trigger-happy about writing off cases."""
    cases = generate_batch(2000, seed=42)
    stop_rate = sum(oracle_decide(c).action == Action.STOP for c in cases) / len(cases)
    assert 0.003 <= stop_rate <= 0.05


def test_oracle_beats_or_ties_all_baselines_on_average_regret():
    """Sanity check on the harness itself: since baselines don't see hidden
    state, the oracle (which does) should never be worse than them."""
    cases = generate_batch(200, seed=8)
    oracle_result = evaluate_policy(cases, lambda c: oracle_decide(c))
    for fn in (always_pursue, fixed_cadence, simple_heuristic):
        baseline_result = evaluate_policy(cases, fn)
        assert oracle_result["summary"]["mean_regret"] <= baseline_result["summary"]["mean_regret"] + 1e-6
