"""
The oracle has access to HiddenState (ground truth) and picks the action
maximizing true expected net value. It is a separate function from any
baseline or agent policy - none of those see HiddenState, only ObservedEvidence.

Probability model is a deliberate simplification, not a claim about real
collections behavior (see SPEC.md 5 - honesty caveat). The shape is:
- WAIT only pays off if a real promise exists and will actually be kept.
- REMIND/ESCALATE each buy a probability boost over the base recoverability,
  but the boost decays with intervention_fatigue (diminishing returns on
  repeated contact) and ESCALATE carries a relationship-harm penalty
  proportional to the customer's true reliability (escalating a reliable
  customer is a worse mistake than escalating an unreliable one).
"""

import math

from env.schemas import Action, Case, HiddenState, PolicyDecision

ACTIONS = list(Action)


def p_recovery(action: Action, hidden: HiddenState) -> float:
    base = hidden.true_recoverability_base
    # Repeated failed contact doesn't just halve effectiveness - it collapses it.
    # A case with intervention_fatigue near 1 (many prior failed attempts) gets
    # almost no further boost from REMIND/ESCALATE, which is what makes STOP
    # reachable at all: without this, WAIT's zero cost trivially beats STOP.
    fatigue_factor = max(0.05, (1 - hidden.intervention_fatigue) ** 1.5)

    if action == Action.STOP:
        return 0.0
    if action == Action.WAIT:
        if hidden.promise_exists:
            return 0.92 if hidden.promise_will_be_kept else 0.12
        return base * 0.6
    if action == Action.REMIND:
        return min(0.95, base + 0.22 * fatigue_factor)
    if action == Action.ESCALATE:
        return min(0.97, base + 0.32 * fatigue_factor)
    raise ValueError(f"unhandled action {action}")


def expected_penalty(action: Action, hidden: HiddenState) -> float:
    if action == Action.ESCALATE:
        # Escalating a reliable customer is a worse mistake than escalating an
        # unreliable one; escalating again after repeated failure compounds it.
        return 150.0 * hidden.true_reliability + 250.0 * hidden.intervention_fatigue
    if action == Action.REMIND:
        return 15.0 + 40.0 * hidden.intervention_fatigue
    return 0.0


def expected_net_value(
    action: Action, hidden: HiddenState, amount: float, action_cost: dict[str, float]
) -> float:
    p = p_recovery(action, hidden)
    cost = action_cost.get(action.value, 0.0)
    penalty = expected_penalty(action, hidden)
    return p * amount - cost - penalty


def oracle_decide(case: Case) -> PolicyDecision:
    best_action, best_ev = None, -math.inf
    for action in ACTIONS:
        ev = expected_net_value(
            action, case.hidden, case.observed.amount, case.observed.action_cost
        )
        if ev > best_ev:
            best_ev, best_action = ev, action
    return PolicyDecision(action=best_action, reason=f"oracle: max EV={best_ev:.2f}")


def true_ev_of(case: Case, action: Action) -> float:
    """EV of a chosen action evaluated against ground truth - used by the
    evaluator to score any policy's decision, not just the oracle's own."""
    return expected_net_value(
        action, case.hidden, case.observed.amount, case.observed.action_cost
    )
