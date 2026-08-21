"""
The deterministic policy engine. No LLM calls here, ever - this module is
what makes "AI ≠ Policy" true rather than just a diagram. It takes whatever
the AI recommended (or failed to produce) and decides what's actually allowed,
in a fixed precedence order:

  1. Hard attempt limit - always wins, even over a confident AI recommendation.
  2. Malformed/unparseable AI output - routed to human, not silently ignored.
  3. Implausible numbers (expected_recovery way beyond the actual amount) -
     rejected even if the output was schema-valid.
  4. Low-confidence recommendations - routed to human rather than trusted.
  5. Otherwise, the AI's recommendation stands.

Every override is logged with why, so the audit trail can show its work.
"""

from typing import Union

from agent.schemas import ParseFailure, RecommendationResult
from env.schemas import Action, ObservedEvidence
from policy.schemas import MerchantPolicy, PolicyOutcome


def apply_policy(
    observed: ObservedEvidence,
    recommendation: Union[RecommendationResult, ParseFailure],
    policy: MerchantPolicy = MerchantPolicy(),
) -> PolicyOutcome:
    if observed.prior_intervention_count >= policy.max_attempts:
        return PolicyOutcome(
            action=Action.STOP,
            reason=f"max attempts ({policy.max_attempts}) reached",
            was_overridden=True,
            override_reason="hard attempt limit - takes precedence over any recommendation",
        )

    if isinstance(recommendation, ParseFailure):
        return PolicyOutcome(
            action=Action.ESCALATE,
            reason="AI output could not be parsed or validated",
            was_overridden=True,
            override_reason=f"parse/validation failure: {recommendation.error}",
        )

    if recommendation.action != Action.ESCALATE:
        implausible_cap = observed.amount * policy.max_plausible_recovery_multiple
        if recommendation.expected_recovery > implausible_cap:
            return PolicyOutcome(
                action=Action.ESCALATE,
                reason="AI-proposed expected_recovery implausible relative to amount",
                was_overridden=True,
                override_reason=(
                    f"expected_recovery {recommendation.expected_recovery} exceeds "
                    f"{policy.max_plausible_recovery_multiple}x amount ({implausible_cap})"
                ),
                source_confidence=recommendation.confidence,
            )

    if (
        recommendation.confidence < policy.min_confidence_for_autonomous_action
        and recommendation.action != Action.ESCALATE
    ):
        return PolicyOutcome(
            action=Action.ESCALATE,
            reason=f"AI recommended {recommendation.action.value} with low confidence",
            was_overridden=True,
            override_reason=(
                f"confidence {recommendation.confidence} < threshold "
                f"{policy.min_confidence_for_autonomous_action}"
            ),
            source_confidence=recommendation.confidence,
        )

    return PolicyOutcome(
        action=recommendation.action,
        reason=recommendation.reason,
        was_overridden=False,
        source_confidence=recommendation.confidence,
    )
