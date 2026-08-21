"""
Baselines a real policy has to beat. All operate on ObservedEvidence only -
never HiddenState. This is what "we compared against realistic simpler
policies" actually means in SPEC.md 7, not a strawman.
"""

from env.schemas import Action, Case, PolicyDecision


def always_pursue(case: Case) -> PolicyDecision:
    return PolicyDecision(action=Action.REMIND, reason="baseline: always pursue")


def fixed_cadence(case: Case, cadence_days: int = 3) -> PolicyDecision:
    due = case.observed.prior_intervention_count == 0 or (
        case.observed.days_past_due % cadence_days == 0
    )
    if due:
        return PolicyDecision(
            action=Action.REMIND, reason=f"baseline: fixed cadence {cadence_days}d, due"
        )
    return PolicyDecision(
        action=Action.WAIT, reason=f"baseline: fixed cadence {cadence_days}d, not due yet"
    )


def simple_heuristic(case: Case, dpd_threshold: int = 14) -> PolicyDecision:
    if case.observed.days_past_due > dpd_threshold:
        return PolicyDecision(
            action=Action.ESCALATE, reason=f"baseline: days_past_due > {dpd_threshold}"
        )
    return PolicyDecision(
        action=Action.REMIND, reason=f"baseline: days_past_due <= {dpd_threshold}"
    )


BASELINES = {
    "always_pursue": always_pursue,
    "fixed_cadence": fixed_cadence,
    "simple_heuristic": simple_heuristic,
}
