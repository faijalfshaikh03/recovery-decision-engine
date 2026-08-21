"""
Minimal case-list UI (SPEC.md 12) - not a dashboard, just enough to make the
decisioning tangible: which cases the system acted on, which it deliberately
left alone, and why, then a drill-down into the full evidence -> extraction
-> recommendation -> policy -> outcome trail for one case. Deliberately kept
separate from webhook_app.py - a demo UI has no business sharing a process
with the production webhook receiver.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from runtime import case_store, db

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# SQLite connections aren't safe to share across threads, and FastAPI runs
# sync route handlers in a threadpool (a different thread per request) -
# each request opens its own connection rather than reusing one at module
# scope. This was a real bug caught while building this: the module-level
# connection worked in scripts (single thread) but crashed under FastAPI
# with "SQLite objects created in a thread can only be used in that same
# thread."
with db.get_connection() as _init_conn:
    db.init_db(_init_conn)

ACTED_STATES = {"PENDING_VERIFICATION", "RECOVERED"}


def _latest_decision_summary(conn, case_id: str) -> dict:
    entries = case_store.get_audit_log(conn, case_id)
    for entry in reversed(entries):
        if entry["event_type"] == "decision":
            try:
                detail = json.loads(entry["detail"])
                rec = detail.get("ai_recommendation", {})
                policy = detail.get("policy_outcome", {})
                return {
                    "action": policy.get("action", "?"),
                    "reason": policy.get("reason", rec.get("reason", "")),
                    "was_overridden": policy.get("was_overridden", False),
                    "confidence": rec.get("confidence"),
                }
            except (json.JSONDecodeError, AttributeError):
                pass
    return {"action": "-", "reason": "no decision yet", "was_overridden": False, "confidence": None}


@app.get("/", response_class=HTMLResponse)
def case_list(request: Request):
    conn = db.get_connection()
    cases = case_store.get_all_cases(conn)
    rows = []
    for case in cases:
        summary = _latest_decision_summary(conn, case.case_id)
        rows.append(
            {
                "case": case,
                "acted": case.state.value in ACTED_STATES,
                **summary,
            }
        )
    total_amount = sum(c.amount for c in cases)
    acted_amount = sum(r["case"].amount for r in rows if r["acted"])
    return templates.TemplateResponse(
        request,
        "case_list.html",
        {
            "rows": rows,
            "n_cases": len(cases),
            "n_acted": sum(1 for r in rows if r["acted"]),
            "n_left_alone": sum(1 for r in rows if not r["acted"]),
            "total_amount": total_amount,
            "acted_amount": acted_amount,
        },
    )


@app.get("/case/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: str):
    conn = db.get_connection()
    case = case_store.get_case(conn, case_id)
    if case is None:
        return HTMLResponse(f"<h1>Case {case_id} not found</h1>", status_code=404)

    entries = case_store.get_audit_log(conn, case_id)
    formatted_entries = []
    for e in entries:
        detail = e["detail"]
        pretty_detail = detail
        if e["event_type"] == "decision":
            try:
                pretty_detail = json.dumps(json.loads(detail), indent=2)
            except json.JSONDecodeError:
                pass
        formatted_entries.append({**e, "pretty_detail": pretty_detail})

    return templates.TemplateResponse(
        request,
        "case_detail.html",
        {"case": case, "entries": formatted_entries},
    )
