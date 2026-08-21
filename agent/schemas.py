from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from env.schemas import Action


class ExtractionResult(BaseModel):
    """What the AI pulled out of the free-text contact note. Nothing here is
    trusted as fact - it's evidence, scored against ground truth separately."""

    promised_date_days_from_now: Optional[int] = None
    promised_amount: Optional[float] = None
    # Explicit, not inferred downstream from date arithmetic: does the note's
    # own wording say the deadline already passed, is still upcoming, or
    # there's no promise at all? Leaving this implicit was a real gap - the
    # recommendation step was under-weighting broken-vs-pending status when
    # it had to infer it indirectly (see SPEC.md milestone notes).
    promise_status: str = "none"  # "none" | "pending" | "broken"
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    sentiment: str = "unclear"
    has_dispute_mention: bool = False


class RecommendationResult(BaseModel):
    """The AI's proposed action. This is a recommendation, not a decision -
    the policy engine (policy/engine.py) decides whether it's allowed."""

    action: Action
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    expected_recovery: float
    recheck_in_days: Optional[int] = None


class ParseFailure(BaseModel):
    """The model's raw output didn't parse into a valid RecommendationResult -
    e.g. an out-of-whitelist action, malformed JSON, or a missing field.
    This is a first-class outcome, not an exception to swallow: the policy
    engine treats it the same as a rejected action (see SPEC.md Failure E)."""

    raw_output: str
    error: str
