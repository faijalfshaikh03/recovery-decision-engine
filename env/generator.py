"""
Synthetic case generator. Deliberately covers the category taxonomy from
SPEC.md 2b (signal quality x value bucket x promise outcome x intervention
history) rather than pure random sampling, so the evaluation is a genuine
stress test of the decision boundary, not an average-case demo.

Each case is a single decision-point snapshot: "here is everything currently
known about one at-risk receivable - what should happen next?" Multi-step
trajectory simulation (advancing a case through the state machine over time)
is a later stretch, not required for oracle/baseline evaluation.
"""

import random
from itertools import product

from env.schemas import (
    Case,
    CaseCategory,
    HiddenState,
    InterventionHistory,
    ObservedEvidence,
    PromiseOutcome,
    SignalQuality,
    ValueBucket,
)

def action_cost_for(amount: float) -> dict[str, float]:
    # WAIT is not actually free: it carries a small opportunity cost of
    # capital tied up, scaling with the amount at stake. Without this, WAIT
    # would always weakly dominate STOP (any nonzero recovery probability at
    # zero cost beats zero), so STOP would never be reachable at all.
    return {"WAIT": max(3.0, 0.03 * amount), "REMIND": 35.0, "ESCALATE": 350.0, "STOP": 0.0}

_CONTACT_NOTE_TEMPLATES = {
    PromiseOutcome.NONE: [
        "No response yet from the customer regarding the outstanding balance.",
        "Reminder sent, customer has not replied so far.",
        "Attempted contact, call went unanswered.",
    ],
    PromiseOutcome.KEPT: [
        "Customer said they'll clear the remaining ₹{amt} within {days} days, "
        "once their procurement team releases the PO.",
        "Spoke to the customer - they confirmed payment of ₹{amt} will land "
        "in about {days} days.",
        "Customer transferred a partial amount today and promised the rest "
        "(₹{amt}) by next week.",
    ],
    PromiseOutcome.BROKEN: [
        "Customer promised ₹{amt} within {days} days last time we spoke, "
        "but the deadline has passed with no payment.",
        "Follow-up call: customer had previously committed to paying ₹{amt} "
        "within {days} days of that conversation - that deadline has now "
        "passed and there's still no sign of payment.",
        "Second broken commitment - customer had promised ₹{amt} but hasn't paid.",
    ],
}

_CONFLICT_SUFFIXES = [
    " They also mentioned disputing part of the invoice.",
    " Note: customer has a history of missed payments despite this call going well.",
    " However, a different team member says the customer sounded evasive.",
]


def _make_contact_note(rng: random.Random, outcome: PromiseOutcome, amount: float,
                        promised_amount, days_offset, conflicting: bool) -> str:
    template = rng.choice(_CONTACT_NOTE_TEMPLATES[outcome])
    note = template.format(amt=int(promised_amount or amount), days=abs(days_offset or 3))
    if conflicting:
        note += rng.choice(_CONFLICT_SUFFIXES)
    return note


def _generate_one(rng: random.Random, case_id: str, category: CaseCategory) -> Case:
    value_bucket = category.value_bucket
    amount = rng.uniform(20_000, 150_000) if value_bucket == ValueBucket.HIGH else rng.uniform(100, 1_500)

    true_reliability = rng.betavariate(2, 2)
    # Real AR portfolios have a genuine minority of near-uncollectible debt -
    # not just "slightly less reliable" customers but distressed cases where
    # recovery is fundamentally unlikely regardless of intervention. Without
    # this archetype, STOP is reachable in theory but never shows up in
    # practice, which would make "sometimes the answer is do nothing" a claim
    # we can't actually demonstrate. The specific corner where STOP is
    # economically reachable is narrow (low value + already exhausted +
    # nothing else going on), so correlate the distressed draw with that
    # corner rather than leaving it as an independent random dimension that
    # would dilute it across all 72 taxonomy combinations.
    is_stop_prone_corner = (
        category.value_bucket == ValueBucket.LOW
        and category.intervention_history == InterventionHistory.ESCALATED
        and category.promise_outcome == PromiseOutcome.NONE
    )
    distressed_p = 0.75 if is_stop_prone_corner else 0.15
    if rng.random() < distressed_p:
        true_recoverability_base = rng.betavariate(1, 6)
    else:
        true_recoverability_base = min(0.95, max(0.02, true_reliability + rng.uniform(-0.15, 0.15)))

    hist_map = {
        InterventionHistory.FIRST_CONTACT: 0,
        InterventionHistory.REPEATED: rng.randint(1, 3),
        InterventionHistory.ESCALATED: rng.randint(2, 5),
    }
    prior_count = hist_map[category.intervention_history]
    outcomes_pool = ["no_response", "partial_payment", "promise_made", "call_declined"]
    prior_outcomes = [rng.choice(outcomes_pool) for _ in range(prior_count)]
    intervention_fatigue = min(1.0, prior_count / 4)

    promise_exists = category.promise_outcome != PromiseOutcome.NONE
    promise_will_be_kept = None
    promised_amount = None
    days_offset = None
    if promise_exists:
        promise_will_be_kept = category.promise_outcome == PromiseOutcome.KEPT
        promised_amount = round(amount * rng.uniform(0.3, 1.0), 2)
        days_offset = rng.randint(2, 10)

    hidden = HiddenState(
        true_reliability=true_reliability,
        true_recoverability_base=true_recoverability_base,
        promise_exists=promise_exists,
        promise_will_be_kept=promise_will_be_kept,
        true_promised_amount=promised_amount,
        true_promised_date_offset_days=days_offset,
        intervention_fatigue=intervention_fatigue,
    )

    # Observed signals derive from hidden truth, degraded per signal_quality.
    sq = category.signal_quality
    noise = {"clean": 0.02, "noisy": 0.18, "conflicting": 0.1}.get(sq.value, 0.0)

    def perturb(x: float) -> float:
        return min(1.0, max(0.0, x + rng.uniform(-noise, noise)))

    if sq == SignalQuality.MISSING:
        historical_promise_keep_rate = None
        on_time_payment_ratio = None
    else:
        historical_promise_keep_rate = perturb(true_reliability)
        on_time_payment_ratio = perturb(true_reliability)

    days_past_due = rng.randint(1, 60)
    recent_partial_payment = None
    if sq == SignalQuality.CONFLICTING:
        # inject a contradiction: decent reliability signal but a broken promise,
        # or a partial payment that doesn't match what was promised
        if rng.random() < 0.5 and promise_exists:
            recent_partial_payment = round((promised_amount or amount) * rng.uniform(0.1, 0.4), 2)
        historical_promise_keep_rate = perturb(min(1.0, true_reliability + 0.35))

    contact_note = _make_contact_note(
        rng, category.promise_outcome, amount, promised_amount, days_offset,
        conflicting=(sq == SignalQuality.CONFLICTING),
    )

    observed = ObservedEvidence(
        case_id=case_id,
        customer_id=f"cust_{case_id}",
        amount=round(amount, 2),
        days_past_due=days_past_due,
        historical_promise_keep_rate=historical_promise_keep_rate,
        on_time_payment_ratio=on_time_payment_ratio,
        prior_intervention_count=prior_count,
        prior_intervention_outcomes=prior_outcomes,
        recent_partial_payment=recent_partial_payment,
        has_open_dispute=(sq == SignalQuality.CONFLICTING and rng.random() < 0.3),
        contact_note=contact_note,
        action_cost=action_cost_for(amount),
    )

    return Case(case_id=case_id, hidden=hidden, observed=observed, category=category)


def generate_batch(n: int, seed: int = 42) -> list[Case]:
    """Generates n cases, cycling deterministically through every category
    combination so the taxonomy is genuinely covered, not just likely-covered."""
    rng = random.Random(seed)
    combos = list(product(SignalQuality, ValueBucket, PromiseOutcome, InterventionHistory))
    cases = []
    for i in range(n):
        sq, vb, po, ih = combos[i % len(combos)]
        category = CaseCategory(
            signal_quality=sq, value_bucket=vb, promise_outcome=po, intervention_history=ih
        )
        cases.append(_generate_one(rng, f"case_{i:05d}", category))
    return cases
