from __future__ import annotations

from pydantic import BaseModel

from env.schemas import Action


class MerchantPolicy(BaseModel):
    max_attempts: int = 4
    min_confidence_for_autonomous_action: float = 0.55
    # expected_recovery more than this multiple of the actual amount is
    # treated as a hallucinated/implausible number, not a bigger opportunity.
    max_plausible_recovery_multiple: float = 1.2


class PolicyOutcome(BaseModel):
    action: Action
    reason: str
    was_overridden: bool
    override_reason: str = ""
    source_confidence: float | None = None
