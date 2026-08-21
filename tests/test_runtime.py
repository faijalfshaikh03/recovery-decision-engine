import pytest

from agent.schemas import ExtractionResult, RecommendationResult
from env.schemas import Action
from runtime import case_service, case_store, db, razorpay_client
from runtime.schemas import CaseState


@pytest.fixture
def conn(tmp_path):
    c = db.get_connection(tmp_path / "test.db")
    db.init_db(c)
    yield c
    c.close()


def make_case(conn, case_id="c1", amount=48000.0):
    return case_store.create_case(
        conn, case_id, "ref-1", amount, "Customer said they'll pay soon.",
        "Test Customer", "test@example.com", "+918123456789",
    )


def test_create_case_starts_overdue(conn):
    case = make_case(conn)
    assert case.state == CaseState.OVERDUE


def test_duplicate_webhook_event_is_rejected_at_db_level(conn):
    first = case_store.record_webhook_event(conn, "evt_1", "payment_link.paid", "{}")
    second = case_store.record_webhook_event(conn, "evt_1", "payment_link.paid", "{}")
    assert first is True
    assert second is False


def test_webhook_for_unknown_payment_link_does_not_crash(conn):
    result = case_service.apply_webhook_event(
        conn, "evt_1", "payment_link.paid",
        {"payload": {"payment_link": {"entity": {"id": "plink_nonexistent"}}}},
    )
    assert result["duplicate"] is False
    assert "error" in result


def test_webhook_for_terminal_case_is_ignored(conn, monkeypatch):
    case = make_case(conn)
    case_store.update_case(conn, case.case_id, razorpay_payment_link_id="plink_x", state=CaseState.RECOVERED.value)

    def fail_verify(*a, **kw):
        raise AssertionError("should not verify an already-terminal case")

    monkeypatch.setattr(case_service, "verify_case", fail_verify)
    result = case_service.apply_webhook_event(
        conn, "evt_1", "payment_link.paid",
        {"payload": {"payment_link": {"entity": {"id": "plink_x"}}}},
    )
    assert result["ignored"] is True


def test_run_decision_stop_transitions_case_to_stopped(conn, monkeypatch):
    case = make_case(conn)
    monkeypatch.setattr(case_service, "extract_evidence", lambda note: ExtractionResult(
        promise_status="none", extraction_confidence=0.9, sentiment="negative", has_dispute_mention=False,
    ))
    monkeypatch.setattr(case_service, "recommend_action", lambda obs, ext: RecommendationResult(
        action=Action.STOP, reason="not worth pursuing", confidence=0.8, expected_recovery=0,
    ))
    case_service.run_decision(conn, case.case_id)
    updated = case_store.get_case(conn, case.case_id)
    assert updated.state == CaseState.STOPPED


def test_run_decision_remind_creates_payment_link_and_verifies(conn, monkeypatch):
    case = make_case(conn)
    monkeypatch.setattr(case_service, "extract_evidence", lambda note: ExtractionResult(
        promise_status="none", extraction_confidence=0.9, sentiment="neutral", has_dispute_mention=False,
    ))
    monkeypatch.setattr(case_service, "recommend_action", lambda obs, ext: RecommendationResult(
        action=Action.REMIND, reason="worth a nudge", confidence=0.8, expected_recovery=40000,
    ))
    monkeypatch.setattr(razorpay_client, "create_payment_link", lambda **kw: {"id": "plink_new"})
    monkeypatch.setattr(razorpay_client, "fetch_payment_link", lambda link_id: {"status": "created", "amount_paid": 0})

    case_service.run_decision(conn, case.case_id)
    updated = case_store.get_case(conn, case.case_id)
    assert updated.razorpay_payment_link_id == "plink_new"
    assert updated.state == CaseState.PENDING_VERIFICATION
    assert updated.prior_intervention_count == 1


def test_run_decision_remind_twice_resends_instead_of_duplicate_create(conn, monkeypatch):
    case = make_case(conn)
    case_store.update_case(conn, case.case_id, razorpay_payment_link_id="plink_existing")

    monkeypatch.setattr(case_service, "extract_evidence", lambda note: ExtractionResult(
        promise_status="none", extraction_confidence=0.9, sentiment="neutral", has_dispute_mention=False,
    ))
    monkeypatch.setattr(case_service, "recommend_action", lambda obs, ext: RecommendationResult(
        action=Action.REMIND, reason="another nudge", confidence=0.8, expected_recovery=40000,
    ))

    def fail_create(**kw):
        raise AssertionError("should not create a second payment link for the same case")

    calls = []
    monkeypatch.setattr(razorpay_client, "create_payment_link", fail_create)
    monkeypatch.setattr(razorpay_client, "resend_notification", lambda link_id, medium="email": calls.append(link_id))
    monkeypatch.setattr(razorpay_client, "fetch_payment_link", lambda link_id: {"status": "created", "amount_paid": 0})

    case_service.run_decision(conn, case.case_id)
    assert calls == ["plink_existing"]


def test_verify_case_marks_recovered_when_paid(conn, monkeypatch):
    case = make_case(conn)
    case_store.update_case(conn, case.case_id, razorpay_payment_link_id="plink_x", state=CaseState.PENDING_VERIFICATION.value)
    monkeypatch.setattr(razorpay_client, "fetch_payment_link", lambda link_id: {"status": "paid", "amount_paid": 4800000})

    case_service.verify_case(conn, case.case_id)
    updated = case_store.get_case(conn, case.case_id)
    assert updated.state == CaseState.RECOVERED


def test_run_decision_on_terminal_case_is_skipped_without_calling_agent(conn, monkeypatch):
    case = make_case(conn)
    case_store.update_case(conn, case.case_id, state=CaseState.STOPPED.value)

    def fail(*a, **kw):
        raise AssertionError("should not call the agent on a terminal case")

    monkeypatch.setattr(case_service, "extract_evidence", fail)
    result = case_service.run_decision(conn, case.case_id)
    assert result["skipped"] is True
