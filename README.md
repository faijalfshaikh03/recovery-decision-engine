# Recovery Decision Engine

Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)

## The problem

Merchants usually know when revenue is at risk — a payment failed, an invoice
is overdue, a subscription didn't renew. What's actually hard isn't
detecting that. It's deciding **whether to intervene, what intervention is
economically justified, and when to stop**, given evidence that's almost
always incomplete and sometimes contradictory.

Razorpay's own Agent Studio already ships execution agents for this space —
Subscription Recovery, Abandoned Cart Conversion, a Receivables Agent that
follows up on unpaid invoices by phone. All of them share one assumption:
*a recovery opportunity exists, so execute a workflow.* None of them publish
anything about the decision layer above that — whether to act at all, how
much intervention is worth spending, and precisely when patience or
escalation stops making sense. That's the specific, narrow gap this project
fills. It is **not** a claim that revenue recovery itself is an unclaimed
category — it obviously isn't. The claim is about depth of execution on a
specific sub-problem, not category novelty.

**First workflow (proof of the engine, not the whole product):**
promise-to-pay recovery on overdue receivables — chosen because it has the
cleanest measurable state transition (a promise is made, then it's either
kept or broken) and the sharpest guardrail story: *a promise is not a
payment, but it's also not a reason to immediately escalate.*

## Architecture

```
Evidence (structured signals + free-text contact note)
        │
        ▼
AI — extraction        (parses the note into structured facts)
        │
        ▼
AI — recommendation     (proposes an action + reasoning + confidence)
        │
        ▼
Deterministic policy    (validates/overrides — zero LLM calls, fully unit-tested)
        │
        ▼
Bounded action           (real Razorpay Payment Links API call, test mode only)
        │
        ▼
Verification              (independently re-polls the API — never trusts
        │                   a webhook or an action's own success response)
        ▼
State update
```

**The AI never directly controls a money-moving API.** It recommends; the
policy engine decides what's actually allowed, in a fixed, explainable
precedence order (`policy/engine.py`):

1. Hard attempt limit → forced `STOP`, wins even over a confident recommendation
2. Malformed/unparseable AI output → forced `ESCALATE`, never silently dropped
3. Implausible `expected_recovery` (>1.2× the actual amount) → forced
   `ESCALATE` even if the output was schema-valid
4. Low-confidence recommendation → forced `ESCALATE` rather than trusted
5. Otherwise, the AI's recommendation stands

Ask this question and the codebase answers it directly: *why didn't you let
the model decide whether the action was permitted?* — because permission is
a safety property, not a reasoning problem. `agent/` recommends;
`policy/engine.py` decides; `runtime/` executes and verifies. They are
physically separate modules, not a diagram.

## Repo layout

| Path | What it is |
|---|---|
| `env/` | Synthetic evaluation environment — case generator, oracle (full hidden-state access), 3 baselines, regret/value metrics |
| `agent/` | AI extraction + recommendation, provider-agnostic (`LLM_PROVIDER=anthropic\|groq`) |
| `policy/` | Deterministic guardrail engine. Zero LLM calls. Fully tested without an API key. |
| `runtime/` | The real system: SQLite state store, real Razorpay client, orchestration, webhook receiver, minimal UI |
| `recon/` | Sandbox reconnaissance scripts and captured evidence from verifying real Razorpay behavior |
| `scripts/` | Runnable entry points (see below) |
| `tests/` | 31 tests, all passing without touching a live API |
| `SPEC.md` | The full technical specification and build log — every milestone, every bug found and fixed, with real numbers |

## Running it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use `source .venv/bin/activate` on Linux/Mac
pip install -r requirements.txt
cp .env.example .env              # fill in your own test-mode keys, never commit .env
pytest tests/ -q                  # 31 tests, no API key required
```

**Test-mode only, everywhere, no exceptions.** Every script that talks to
Razorpay checks the key prefix and hard-refuses to run against anything that
isn't `rzp_test_...`. This project never touches real money.

Entry points, roughly in the order they matter:

- `scripts/run_baseline_eval.py` — 2,000 synthetic cases, oracle vs. 3 baselines
- `scripts/run_agent_eval.py [n]` — the real AI pipeline against n synthetic cases
- `scripts/run_live_demo.py` — creates one real case and runs it through the
  actual system (needs `runtime/webhook_app.py` running to observe the
  resulting payment webhook)
- `runtime/ui_app.py` — the case-list UI (`uvicorn runtime.ui_app:app --port 8000`)

## Evaluation — synthetic environment (2,000 cases)

Headline metric is value/regret, not raw agreement (see *why* below):

| policy | oracle agreement | mean regret | % of oracle value | false-escalation rate |
|---|---|---|---|---|
| oracle | 100.0% | 0.00 | 100.0% | 0.0% |
| always_pursue | 33.1% | 5776.88 | 80.8% | 0.0% |
| fixed_cadence | 35.8% | 7994.79 | 73.4% | 0.0% |
| simple_heuristic | 31.4% | 4657.63 | **84.5%** | **53.5%** |

`simple_heuristic` gets closest to the oracle on raw value but only by
escalating over half the time when it shouldn't. That's the honest reason
`false_escalation_rate` is tracked as its own number instead of being folded
into one blended score — value captured alone would make this baseline look
like the best one.

A real bug was caught building this harness before it produced a single
number worth trusting: the first version of the economics **never** produced
`STOP` as optimal — 0 times in 10,000 simulated cases — because `WAIT` had
near-zero cost, so any nonzero recovery probability trivially beat doing
nothing. Fixed by giving `WAIT` a real carrying cost and correlating the
"distressed debt" archetype with the specific corner where stopping is
actually rational. `STOP` now appears at ~1% of cases — rare, but real and
demonstrable, which is the more believable story anyway.

## Evaluation — the real AI pipeline (25 live cases)

This is the part that's hardest to fake and most worth reading closely.

| run | mean regret | oracle agreement |
|---|---|---|
| first real run | 7141.57 | 52.0% |
| after fixing the extraction schema/prompt | 3840.29 | 52.0% |
| after fixing an ambiguous data-generator template | 1539.04 | 52.0% |

**Oracle agreement stayed at exactly 52% across all three runs while regret
fell 78%.** That's not a typo — it's a live, unstaged demonstration of why
regret is the metric that actually reveals what changed. Agreement rate
would have shown zero improvement.

What actually happened: the two worst-regret cases both had correct
extraction (near-zero amount error) but bad recommendations — `REMIND` on a
promise that was still credible and pending, `WAIT` on a promise that had
already broken. Root-caused it: `ExtractionResult` never explicitly captured
pending-vs-broken, so the recommendation step had to infer it indirectly and
was under-weighting the signal. First fix (explicit `promise_status` field +
prompt) cut regret 46%. One case was still unchanged after that fix — turned
out the actual bug was in **our own synthetic data template**, not the
model: a "broken promise" note read *"customer said 'definitely by 4 days'
previously, still no sign of payment"* — genuinely ambiguous wording even to
a careful human reader about whether that deadline had passed. Rewrote the
template to be unambiguous, reran, regret dropped the rest of the way.
Full detail in `SPEC.md §13d`.

## Failure lab — tested against the live system, not just mocks

| # | Failure | Result |
|---|---|---|
| Duplicate webhook | **Confirmed live.** Replayed a real captured `payment_link.paid` event a second time. Correctly flagged as duplicate at the database level (`webhook_events.event_id` is a `PRIMARY KEY`), zero reprocessing. |
| Out-of-order webhook | **Confirmed live.** Sent a stale event for an already-`RECOVERED` case. Correctly ignored — state never regressed. |
| Invalid signature | **Confirmed live.** A corrupted signature was rejected before it ever reached the state engine or touched the database. |
| Invalid/malformed AI output | Proven via unit tests (hand-crafted bad JSON, out-of-whitelist actions) — not observed to occur naturally with real model output in our live sample. |
| Low-confidence recommendation | **Attempted live twice, honestly not triggered.** Two deliberately ambiguous cases both came back above the confidence threshold (0.65, 0.73). Not reframed as a success — reported as a real finding: this model's self-reported confidence runs higher than the actual ambiguity warrants, which is exactly why the guardrail also has an *objective* check (implausible `expected_recovery`) that doesn't depend on the model grading its own uncertainty. |
| Verification ambiguous | **Confirmed live.** A case sat correctly in `PENDING_VERIFICATION` (`status=created, amount_paid=0`) rather than assuming success, until an independent poll confirmed `status=paid`. |

Two rows didn't resolve the way a tidier demo would want. Reported as-is —
see `SPEC.md §13f` for the full discipline note on why that matters here
specifically.

## One full real end-to-end run

1. Created one case — ₹48,000, 22 days overdue, no contact yet
2. AI recommended `REMIND` (correct reasoning: no promise, first outreach,
   negative sentiment) → policy passed it through → real
   `POST /payment_links` created a live test-mode Payment Link → case moved
   to `PENDING_VERIFICATION` → immediately polled the real API and confirmed
   `status=created, amount_paid=0`
3. Paid the real link through actual browser checkout
4. A real Razorpay webhook arrived → signature verified → matched to the
   case → **independently re-polled the API rather than trusting the
   webhook payload** → confirmed `status=paid, amount_paid=4800000` → case
   → `RECOVERED`

Full audit trail, in order: `decision → action_executed → verification
(unpaid) → webhook → verification (paid) → state_transition`. That's the
architecture diagram above, verified true of the running code.

## What broke, beyond the headline regret bug

- **SQLite thread-safety bug in the UI.** A single module-level connection
  crashed under FastAPI's threadpool (`sqlite3.ProgrammingError: SQLite
  objects created in a thread can only be used in that same thread`) —
  worked fine in single-threaded scripts, broke under real HTTP concurrency.
  Fixed by opening a connection per request.
- **A dependency API changed under us.** `Jinja2Templates.TemplateResponse`'s
  expected argument order changed in the installed Starlette version; the
  old calling convention failed several layers down inside Jinja2's template
  cache with a confusing `TypeError: unhashable type: 'dict'`, not at the
  call site. Traced it to the actual root cause instead of guessing.
- **Test-mode sandbox quirks nobody's docs mentioned**, all caught by
  actually running against the sandbox instead of trusting documentation:
  Razorpay rejects phone numbers with recurring digits; the "universal" test
  card everyone assumes works (`4111 1111 1111 1111`) is rejected as
  *international* on India checkout; a partially-paid link can't be
  cancelled; Razorpay blocklists known public webhook-testing hostnames
  (`webhook.site`, `loca.lt`) as webhook destinations.

## Honesty notes

- The synthetic environment is a decision environment we constructed to
  have known ground truth, not an empirical model of real-world collections
  behavior. The claim is narrow and defensible: *given this simulated
  environment, how efficiently does the agent infer the right action from
  partial, noisy evidence?*
- Every number in this README came from an actual run, not a projection.
  Reports are saved in `recon/` (`baseline_eval_report.json`,
  `agent_eval_report.json`, `agent_eval_report_before.json`) if you want to
  check the raw data yourself.

## What's explicitly out of scope for this build

Subscriptions, abandoned cart, voice, WhatsApp, multi-channel orchestration,
fraud detection, multi-agent dashboards. The Razorpay integration is
deliberately thin — Payment Links only, no Invoices/Orders/Subscriptions/
Customers API. See `SPEC.md §11–12` for the full reasoning.
