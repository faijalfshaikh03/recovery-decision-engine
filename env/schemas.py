from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Action(str, Enum):
    WAIT = "WAIT"
    REMIND = "REMIND"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


class SignalQuality(str, Enum):
    CLEAN = "clean"
    NOISY = "noisy"
    MISSING = "missing"
    CONFLICTING = "conflicting"


class ValueBucket(str, Enum):
    HIGH = "high"
    LOW = "low"


class PromiseOutcome(str, Enum):
    NONE = "none"
    KEPT = "kept"
    BROKEN = "broken"


class InterventionHistory(str, Enum):
    FIRST_CONTACT = "first_contact"
    REPEATED = "repeated"
    ESCALATED = "escalated"


class CaseCategory(BaseModel):
    signal_quality: SignalQuality
    value_bucket: ValueBucket
    promise_outcome: PromiseOutcome
    intervention_history: InterventionHistory


class HiddenState(BaseModel):
    """Ground truth. Oracle and evaluator only - never shown to a policy."""

    true_reliability: float
    true_recoverability_base: float
    promise_exists: bool
    promise_will_be_kept: Optional[bool] = None
    true_promised_amount: Optional[float] = None
    true_promised_date_offset_days: Optional[int] = None
    intervention_fatigue: float


class ObservedEvidence(BaseModel):
    """The only thing a policy/agent is allowed to see."""

    case_id: str
    customer_id: str
    amount: float
    days_past_due: int
    historical_promise_keep_rate: Optional[float] = None
    on_time_payment_ratio: Optional[float] = None
    prior_intervention_count: int
    prior_intervention_outcomes: list[str]
    recent_partial_payment: Optional[float] = None
    has_open_dispute: bool
    contact_note: str
    action_cost: dict[str, float]


class Case(BaseModel):
    case_id: str
    hidden: HiddenState
    observed: ObservedEvidence
    category: CaseCategory


class PolicyDecision(BaseModel):
    action: Action
    reason: str = ""
