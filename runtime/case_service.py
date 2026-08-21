"""
The orchestration layer: ties env schemas, the agent, the policy engine, and
the real Razorpay client into the actual running system. This is where
"AI reasoning -> deterministic policy -> bounded action -> Razorpay API ->
verification -> state update" (SPEC.md 1) stops being a diagram.
"""

import json
import sqlite3
from typing import Optional

from agent.extract import extract_evidence
from agent.recommend import recommend_action
from agent.schemas import ExtractionResult, ParseFailure
from env.generator import action_cost_for
from env.schemas import Action, ObservedEvidence
from policy.engine import apply_policy
from runtime import case_store, razorpay_client
from runtime.schemas import CaseState


def _observed_from_case(case) -> ObservedEvidence:
    return ObservedEvidence(
        case_id=case.case_id,
        customer_id=case.reference_id,
        amount=case.amount,
        days_past_due=case.days_past_due,
        historical_promise_keep_rate=None,
        on_time_payment_ratio=None,
        prior_intervention_count=case.prior_intervention_count,
        prior_intervention_outcomes=[],
        recent_partial_payment=None,
        has_open_dispute=False,
        contact_note=case.contact_note,
        action_cost=action_cost_for(case.amount),
    )


def run_decision(conn: sqlite3.Connection, case_id: str) -> dict:
    """The core loop for one case: extract -> recommend -> policy -> act."""
    case = case_store.get_case(conn, case_id)
    if case is None:
        raise ValueError(f"unknown case_id {case_id}")
    if case.state.is_terminal:
        case_store.log_audit(conn, case_id, "decision", f"skipped - case is terminal ({case.state.value})")
        return {"skipped": True, "reason": "terminal state"}

    observed = _observed_from_case(case)
    extraction = extract_evidence(observed.contact_note)
    recommendation = recommend_action(observed, extraction)
    outcome = apply_policy(observed, recommendation)

    case_store.log_audit(
        conn,
        case_id,
        "decision",
        json.dumps(
            {
                "extraction": extraction.model_dump() if isinstance(extraction, ExtractionResult) else {"parse_failure": extraction.error},
                "ai_recommendation": recommendation.model_dump() if not isinstance(recommendation, ParseFailure) else {"parse_failure": recommendation.error},
                "policy_outcome": outcome.model_dump(),
            }
        ),
    )

    _apply_action(conn, case_id, outcome.action, outcome.reason, extraction)
    return {"skipped": False, "action": outcome.action.value, "was_overridden": outcome.was_overridden}


def _apply_action(conn, case_id: str, action: Action, reason: str, extraction) -> None:
    if action == Action.STOP:
        case_store.update_case(conn, case_id, state=CaseState.STOPPED.value)
        case_store.log_audit(conn, case_id, "state_transition", f"-> STOPPED ({reason})")
        return

    if action == Action.WAIT:
        if isinstance(extraction, ExtractionResult) and extraction.promise_status == "pending":
            case_store.update_case(
                conn,
                case_id,
                state=CaseState.WAITING_FOR_PROMISE.value,
                promised_amount=extraction.promised_amount,
                promised_date_days_from_now=extraction.promised_date_days_from_now,
            )
            case_store.log_audit(conn, case_id, "state_transition", f"-> WAITING_FOR_PROMISE ({reason})")
        else:
            case_store.log_audit(conn, case_id, "state_transition", f"stayed - WAIT with no active promise ({reason})")
        return

    # REMIND / ESCALATE both use the same tool (SPEC.md 11 - thin integration
    # scope): create a Payment Link if the case doesn't have one yet,
    # otherwise resend the notification rather than creating a duplicate.
    case = case_store.get_case(conn, case_id)
    if case.razorpay_payment_link_id is None:
        link = razorpay_client.create_payment_link(
            amount_paise=int(round(case.amount * 100)),
            description=f"Recovery case {case.reference_id}" + (" (escalated)" if action == Action.ESCALATE else ""),
            reference_id=case.reference_id,
            customer_name=case.customer_name,
            customer_email=case.customer_email,
            customer_contact=case.customer_contact,
        )
        case_store.update_case(
            conn, case_id,
            razorpay_payment_link_id=link["id"],
            prior_intervention_count=case.prior_intervention_count + 1,
            state=CaseState.PENDING_VERIFICATION.value,
        )
        case_store.log_audit(conn, case_id, "action_executed", f"created payment link {link['id']} ({action.value}: {reason})")
    else:
        razorpay_client.resend_notification(case.razorpay_payment_link_id)
        case_store.update_case(
            conn, case_id,
            prior_intervention_count=case.prior_intervention_count + 1,
            state=CaseState.PENDING_VERIFICATION.value,
        )
        case_store.log_audit(conn, case_id, "action_executed", f"resent notification for {case.razorpay_payment_link_id} ({action.value}: {reason})")

    verify_case(conn, case_id)


def verify_case(conn: sqlite3.Connection, case_id: str) -> None:
    """API success != business success (SPEC.md Failure F): after any action
    that touched Razorpay, independently poll the real state rather than
    assume the action achieved what it intended."""
    case = case_store.get_case(conn, case_id)
    if case is None or case.razorpay_payment_link_id is None:
        return
    link = razorpay_client.fetch_payment_link(case.razorpay_payment_link_id)
    status = link.get("status")
    case_store.log_audit(conn, case_id, "verification", f"polled payment link: status={status} amount_paid={link.get('amount_paid')}")

    if status == "paid":
        case_store.update_case(conn, case_id, state=CaseState.RECOVERED.value)
        case_store.log_audit(conn, case_id, "state_transition", "-> RECOVERED (verified via independent poll)")
    elif status in ("cancelled", "expired"):
        case_store.update_case(conn, case_id, state=CaseState.STOPPED.value)
        case_store.log_audit(conn, case_id, "state_transition", f"-> STOPPED (link {status})")
    # otherwise stays PENDING_VERIFICATION until the next webhook or recheck


def apply_webhook_event(conn: sqlite3.Connection, event_id: str, event_type: str, payload: dict) -> dict:
    """Failure A (duplicate) is handled by the DB PRIMARY KEY in
    record_webhook_event. Failure B (out-of-order) is handled by never
    trusting the event content directly - we always re-poll the actual
    current state before applying a transition (Failure D)."""
    is_new = case_store.record_webhook_event(conn, event_id, event_type, json.dumps(payload))
    if not is_new:
        return {"duplicate": True}

    payment_link_entity = (
        payload.get("payload", {}).get("payment_link", {}).get("entity", {})
    )
    link_id = payment_link_entity.get("id")
    if not link_id:
        return {"duplicate": False, "error": "no payment_link id in payload"}

    case = case_store.get_case_by_payment_link(conn, link_id)
    if case is None:
        return {"duplicate": False, "error": f"no case for payment_link {link_id}"}

    case_store.log_audit(conn, case.case_id, "webhook", f"{event_type} received (event_id={event_id})")

    if case.state.is_terminal:
        case_store.log_audit(conn, case.case_id, "webhook", f"ignored - case already terminal ({case.state.value})")
        return {"duplicate": False, "case_id": case.case_id, "ignored": True}

    # Don't trust the webhook payload's status directly - independently
    # verify against the API before changing state (Failure D discipline).
    verify_case(conn, case.case_id)
    return {"duplicate": False, "case_id": case.case_id}
