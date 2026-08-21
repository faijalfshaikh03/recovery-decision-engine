from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class CaseState(str, Enum):
    OVERDUE = "OVERDUE"
    CONTACTED = "CONTACTED"
    PROMISE_RECEIVED = "PROMISE_RECEIVED"
    WAITING_FOR_PROMISE = "WAITING_FOR_PROMISE"
    PROMISE_BROKEN = "PROMISE_BROKEN"
    RE_EVALUATE = "RE_EVALUATE"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    RECOVERED = "RECOVERED"
    STOPPED = "STOPPED"

    @property
    def is_terminal(self) -> bool:
        return self in (CaseState.RECOVERED, CaseState.STOPPED)


class RuntimeCase(BaseModel):
    case_id: str
    reference_id: str
    amount: float
    state: CaseState
    razorpay_payment_link_id: Optional[str] = None
    days_past_due: int = 0
    contact_note: str
    prior_intervention_count: int = 0
    promised_amount: Optional[float] = None
    promised_date_days_from_now: Optional[int] = None
    customer_name: str
    customer_email: str
    customer_contact: str
    created_at: float
    updated_at: float


class AuditLogEntry(BaseModel):
    case_id: str
    at: float
    event_type: str  # "decision" | "webhook" | "verification" | "state_transition"
    detail: str
