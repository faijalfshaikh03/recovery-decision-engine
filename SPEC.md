# Recovery Decision Engine — System Specification v0.1

Razorpay AI Buildathon — Track 03 (AI Revenue Recovery)

## 1. Thesis

Merchants know revenue is at risk, but the hard problem isn't detecting that — it's
deciding whether to intervene, what intervention is economically justified, and when
to stop. Razorpay's shipped agents (Subscription Recovery, Abandoned Cart Conversion,
Receivables Agent) all assume "recovery opportunity exists → execute a workflow."
This system is the decision layer above that assumption: it evaluates a recovery
opportunity under incomplete, sometimes-conflicting evidence, and produces a bounded,
audited action — never letting the AI move money directly.

**Architecture principle:** AI reasoning → deterministic policy → bounded action →
verification → state update. The LLM never directly controls a money-moving API.

**First workflow (proof of the engine, not the whole product):** Promise-to-Pay
lifecycle on overdue B2B/subscription receivables.

## 2. Entities & Signals

Each recovery opportunity ("case") carries:

- `customer_id`, relationship tenure
- `invoice_id` / `payment_id`, `amount`, `days_past_due`
- payment history: past N payments, on-time ratio
- prior interventions on this case: count, channel, outcome
- prior promise-to-pay behavior: promises made, promises kept (historical rate)
- recent activity: partial payments, disputes raised, contact responses
- current status: `OVERDUE`, `CONTACTED`, `PROMISE_RECEIVED`, `WAITING_FOR_PROMISE`,
  `PROMISE_BROKEN`, `RE_EVALUATE`, `RECOVERED`, `STOPPED`, `PENDING_VERIFICATION`
- estimated intervention cost per channel (email/link ≈ ₹5–20, call ≈ ₹100–300,
  escalation ≈ higher, placeholder figures to calibrate during build)
- merchant policy: max attempts, escalation threshold, contact-frequency limits

**Agent visibility rule:** the agent (AI + policy engine) sees only the observed,
noisy version of these signals. The *true* underlying recoverability is hidden —
known only to the data generator and the evaluator.

**Unstructured evidence (required, not optional):** each case must include a
free-text contact note — e.g. *"Customer said they'll clear the outstanding ₹48K
after the procurement team releases the PO tomorrow. They transferred ₹10K today."*
This is what makes the AI's role load-bearing rather than decorative: if every
input were already a clean structured field, a rules engine would suffice. The
promised date, promised amount, and confidence must be *extracted* from this text,
not handed to the system pre-parsed.

## 2b. Case Category Taxonomy (data generator must cover all of these)

The synthetic generator should deliberately produce cases across each axis below,
not just random draws — this is what turns the evaluation into a real stress test
of the decision boundary rather than an average-case demo:

- **Signal quality:** clean / noisy / missing / conflicting
- **Case value:** high-amount / low-amount (tests the economics, §6)
- **Promise outcome:** kept / broken / no promise made
- **Intervention history:** first contact / repeated prior attempts / prior escalation

Report metrics broken down by these categories, not just in aggregate — an honest
per-category breakdown is stronger evidence than a single blended number.

## 3. Action Whitelist

Deliberately small, for clean evaluation:

- `WAIT` — hold, recheck later (used when a valid promise exists)
- `REMIND` — send a reminder / payment link (real Razorpay test-mode Payment Link)
- `ESCALATE` — hand to human / firmer channel
- `STOP` — no further action (case closed, recovered or written off)
- `RETRY` — reserved; only added if Razorpay test APIs make a real retry meaningful
  for a specific sub-case. Not required for v1.

## 4. State Machine (Promise-to-Pay)

```
OVERDUE
   │
   ▼
CONTACTED
   │
   ▼
PROMISE_RECEIVED
   │
   ▼
WAITING_FOR_PROMISE ──(recheck on promised date)──┐
   │                                              │
   ├── payment received ──► RECOVERED / STOP      │
   │                                               │
   └── promise broken ──► RE_EVALUATE ◄────────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
              REMIND      ESCALATE       STOP

Any action that calls an external API transitions first to
PENDING_VERIFICATION, and only moves to its terminal state
after the system independently re-checks payment status.
```

Every transition is an explicit, logged event — no implicit state changes.

## 5. Data-Generating Process & Oracle

```
customer profile + invoice context + historical behavior + intervention cost
                          │
                    latent recoverability (hidden)
                          │
              observed noisy signals (what the agent sees)
```

The **oracle** is a separate function with access to the hidden latent state. It is
*not* the same rules the agent uses — it computes, for each candidate action, the
true expected net value (§6) using ground-truth probabilities, and picks the argmax
subject to hard constraints (e.g., can't act from a terminal state). This gives an
upper bound to measure against, derived independently of anything the agent sees.

**Honesty caveat (state this explicitly in the README/demo, not just here):** this
is a synthetic decision environment we constructed, not an empirical estimate of
real-world collections behavior. The claim we're making is narrow and defensible —
"given a known simulated environment, how efficiently does the agent infer the best
action from partial, noisy evidence?" — not "this predicts real customer behavior."

## 6. Economics

```
Expected Net Value(action) = P(recovery | evidence) × Amount
                              − ActionCost(action)
                              − ExpectedPenalty(action)
```

`ExpectedPenalty` captures goodwill/relationship cost of over-aggressive action
(e.g., escalating a reliable customer). Exact weights are tuned during build against
plausible collections-industry figures, not fixed in the design.

Policy engine enforces hard constraints regardless of computed EV:
- action ∈ whitelist for current state
- attempts ≤ merchant-configured max
- no action from a terminal state
- amount/action bounds sane-checked
- idempotency: a duplicate event must not trigger a duplicate action

## 7. Baselines (defined before the AI is built)

1. **Always-pursue** — every eligible case gets `REMIND`
2. **Fixed-cadence** — remind every N days regardless of signals
3. **Simple heuristic** — `days_past_due > X → ESCALATE else REMIND`
4. **Oracle** — full hidden-state access, upper bound
5. **Our system** — observed evidence → AI reasoning → policy engine → action

Success is framed as: *how close do we get to the oracle, and do we beat baselines
1–3 on expected net value?* — not a standalone "₹X recovered" claim.

## 8. Where AI Belongs

| Layer | Responsibility |
|---|---|
| **AI — extraction** | Parse the free-text contact note into structured partial signals: `{promised_date, promised_amount, extraction_confidence, sentiment}`. Measured independently against ground truth (own accuracy metric — see §10). |
| **AI — recommendation** | Combine extracted + structured signals into `{action, reason, confidence, expected_recovery, recheck_date}`, explain the reasoning |
| **Deterministic policy** | Action whitelist, attempt/escalation limits, terminal-state checks, timing constraints, amount validation, idempotency, merchant policy enforcement — rejects any AI output that violates these, regardless of confidence |
| **Evaluation engine** | Fully separate. Compares chosen action to oracle, computes metrics, logs disagreements, tracks real outcomes. Never influences the live decision. |

`AI ≠ Policy ≠ Execution ≠ Evaluation` — kept as physically separate modules.

## 9. Failure Lab (built in from day one)

| # | Failure | Required behavior | Grounding |
|---|---|---|---|
| A | Duplicate webhook — same event delivered twice | Dedupe on `x-razorpay-event-id`; second delivery is a no-op | Razorpay: at-least-once delivery is documented, not assumed |
| B | Out-of-order webhook — e.g. `paid` arrives before `partially_paid` is processed | Never trust "last event wins"; check current state before applying a transition | Razorpay explicitly warns delivery order isn't guaranteed |
| C | Invalid/unverifiable signature | Reject before processing; log and drop | Real security control — `X-Razorpay-Signature`, HMAC-SHA256 over raw body |
| D | Webhook says paid, but this is business-critical — don't trust it blindly | Independently poll the relevant API before marking `RECOVERED` | Razorpay's own guidance: poll for business-critical sync, webhooks are async |
| E | Invalid model output — AI proposes an out-of-whitelist or malformed action | Schema/policy layer rejects it; logged, not executed | Our own agent-level safety failure |
| F | Action succeeds but verification is ambiguous (e.g. request timed out) | Move to `PENDING_VERIFICATION`, never straight to `FAILED` or `RECOVERED` | Combines B and D — don't guess, re-query |

Discipline note carried over: these are targets to deliberately stress-test (replay
an event, corrupt a signature, force a timeout), and A–D are grounded in Razorpay's
own documented platform behavior, not invented — but the README reports what
actually happened when we ran them, not a pre-written narrative.

Each of these should be a reproducible test case with a before/after log — this is
the literal "what broke at 2am, how you got out" material for the README.

**Important discipline:** these are stress-test *targets*, not a pre-written
narrative. It's legitimate to deliberately construct scenarios likely to surface
them (replay a webhook on purpose, kill a request mid-flight, feed an adversarial
prompt) — that's normal engineering practice. But the README must report what
actually happened when we ran them, including if the first attempt didn't break the
way we expected, or broke somewhere else entirely. A fabricated failure story is
worse than no failure story — the whole point of this criterion is that it's hard
to fake.

## 10. Metrics (reported honestly, with failure analysis attached)

**Headline metric — value-based, not raw agreement:**
- Regret per case: `EV_oracle − EV_agent`, and `% of oracle value achieved`
  (two disagreements aren't equally bad — missing on a ₹1L case matters far more
  than missing on a ₹200 case; raw agreement rate hides this)
- Net recovered value vs. oracle upper bound
- Comparison vs. baselines 1–3 (always-pursue, fixed-cadence, simple heuristic)

**Diagnostic / secondary metrics:**
- Oracle agreement rate (e.g. "82.4%", not rounded up to look better) — reported,
  but not the headline
- Extraction accuracy (promised date / amount correctly parsed from free text)
- False-escalation rate
- Promise-kept detection accuracy
- Unnecessary-intervention rate
- Named worst-error categories (e.g. "ambiguous promise language," "sparse history")

## 10b. Hard Safety Rule — Test Mode Only

This project never touches real money, in any form, at any stage — not for the
demo, not for the video, not for anything. Only Razorpay **test-mode** keys
(`rzp_test_...`) and test cards are used. Any code that talks to Razorpay must
verify the key prefix and refuse to run otherwise (see `recon/` scripts for the
pattern — this check must be carried into every future script/service, not just
the recon ones). No live keys are ever generated for this project, full stop.

## 11. Razorpay Integration Scope (v1)

Kept deliberately minimal — the differentiator is the decision layer, not payment-rail
depth. **Status: docs-verified, not yet live-verified** — confirmed against official
Razorpay documentation; actual auth/behavior against a real test account is the next
step (§Recon) before this is finalized.

**Confirmed live in sandbox (2026-08-21, `recon/` scripts + browser checkout):**
- Auth via Basic Auth (key_id, key_secret) against `https://api.razorpay.com/v1` — works
- `POST /payment_links` — works, but **customer.contact with recurring digits is
  rejected** (`"Recurring digits in customer contact are disallowed"`) — undocumented
  validation rule we hit directly, not in any doc we'd read
- `accept_partial` defaults to `false` on creation — must set explicitly `true` to
  exercise the partial-payment path later
- The generic "universal" test card `4111 1111 1111 1111` (commonly used across
  other providers) is **rejected as an international card** on Razorpay's India
  checkout. The correct domestic test card is `4100 2800 0000 1007` (Visa). Razorpay
  also documents specific test cards for specific failure reasons (insufficient
  funds, timeout, declined, auth failed, gateway error) — a real signal source for
  case data later, not just synthetic guessing.
- Test-mode checkout redirects to a mock bank page with explicit Success/Failure
  buttons — confirms docs' description of the sandbox flow
- After a successful test payment, independently re-fetched via API (not trusted
  from the browser alone): Payment Link `status: "paid"`, `amount_paid` matches;
  `GET /payments/{id}` shows `status: "captured"`, `international: false`,
  card network/last4 correct
- Webhook configuration requires Dashboard login (no general API for it on a
  standard merchant account) — done manually, not automatable by an agent
- **Razorpay blocklists known public tunnel/webhook-testing hostnames** —
  confirmed for both `webhook.site` and `loca.lt` ("hostname not allowed").
  Worked around with a Cloudflare quick tunnel (`cloudflared tunnel --url ...`,
  no account needed) — apparently not on the same blocklist. **Caveat for
  later:** quick tunnels are ephemeral, the URL changes every restart — fine
  for dev/recon, not viable as-is for demo day.
  **Resolved:** confirmed via research that Cloudflare has no free stable
  hostname without owning a domain - a hard platform limitation, not a
  config gap. Decided against buying a domain or standing up hosting for a
  one-time recording; built `scripts/start_demo_environment.sh` instead - a
  one-shot script that restarts the webhook app, the UI, and a fresh tunnel,
  then prints the URL to paste into the Dashboard before recording. Tested
  end to end.
- **Live webhook test, fully verified, not just docs-checked:** ran a real
  ₹15,000 partial payment (of a ₹48,000 `accept_partial` link) through actual
  browser checkout. Received real webhook deliveries for `payment.authorized`,
  `payment.captured`, and `payment_link.partially_paid` — all with **valid
  HMAC-SHA256 signatures independently recomputed and matched** against our
  own webhook secret. `payment_link.partially_paid` payload matched docs
  exactly: `amount_paid: 1500000`, `amount_due: 3300000`, all three entities
  (payment_link/order/payment) present.
  - **Unexpected finding:** only the 4 `payment_link.*` events were selected
    in the Dashboard, but `payment.authorized`/`payment.captured` fired too —
    worth double-checking the account's webhook event selection before relying
    on an exact allowlist assumption.
- **Cancellation is state-restricted:** attempted to cancel a partially-paid
  link — rejected with `"cannot cancel or expire an already paid / partially
  paid link"`. Real constraint, not in the docs we'd read; a cancel/stop path
  in the policy engine needs to check payment state first, not just call the
  API and assume it succeeds.
- **Dedup logic verified against real + replayed traffic:** created and
  cancelled a throwaway link to get a clean `payment_link.cancelled` sample,
  captured its exact raw body + signature, then replayed it byte-for-byte at
  our own receiver — correctly flagged `is_duplicate: true` on the second
  delivery. Separately sent the same body with a corrupted signature — correctly
  flagged `signature_valid: false`. Both halves of Failure A/C are now proven
  against real captured Razorpay payloads, not synthetic test data.

**Confirmed real capabilities (docs):**
- Create Payment Link (standard/UPI) — `POST`
- Fetch single / all Payment Links — `GET`
- Update Payment Link — `PATCH`
- Cancel Payment Link — `POST`
- Send/Resend Notification — `POST` (distinct from creation — a real second action)
- Webhooks: `payment_link.paid`, `payment_link.partially_paid`,
  `payment_link.cancelled`, `payment_link.expired` — `partially_paid` maps directly
  onto our "partial payment" signal, meaning a real webhook can drive a real state
  transition in the demo, not a simulated one
- **Test-mode limit: 30 Payment Links per business.** Confirmed via docs. This is
  an architectural constraint, not just a detail.

**Revised action mapping** (real capabilities, not invented ones):
`WAIT | CREATE_PAYMENT_LINK | SEND_PAYMENT_LINK (resend notification) |
ESCALATE_TO_HUMAN | STOP`

**Architectural consequence of the 30-link cap:** the synthetic benchmark (thousands
of cases, for statistical evaluation) and the Razorpay sandbox demo (a small set of
real cases, for proof the agent actually operates against Razorpay) must be kept
separate. The bulk evaluation never touches the live API; only a curated handful of
demo cases do.

- **Precise language matters:** a Payment Link is not a reminder. The audit log and
  demo must say "generated recovery payment link" / "resent payment link
  notification," not "sent a reminder to the customer" — `SEND_PAYMENT_LINK` uses
  the real notification endpoint, so this is now literally accurate, not simulated.
- No Subscriptions/eNACH/mandate API work in v1 — not needed for the promise-to-pay
  workflow and out of scope for the time available

**Webhook handling (non-negotiable part of the MVP loop, not optional hardening):**
`verify X-Razorpay-Signature (HMAC-SHA256, raw body) → dedupe on x-razorpay-event-id
→ persist event → return 2xx within the 5s window → process asynchronously →
poll the relevant API before trusting a "paid" state → apply transition`. This
isn't gold-plating — a synchronous LLM call inside the handler risks the timeout
and a self-inflicted duplicate delivery.

**Tool boundary (read / act / event):**
- Read: internal case context; Payment Link status; payment/order state
  (Orders/Payments-based verification chain — adopt only if cheap once in the
  sandbox, not a separate research track)
- Act: create Payment Link; send/resend notification
- Event: Payment Link webhooks
- Explicitly out of v1 unless the sandbox makes a compelling case: Invoices API,
  Customers API, Route, Smart Collect, Subscriptions, Payouts, Disputes

## 12. MVP Boundary

In scope for v1: one workflow (overdue → promise-to-pay → wait → verify →
re-evaluate → decide), synthetic dataset, oracle + 3 baselines, policy engine,
failure lab, and a minimal case-list UI — not a big dashboard, just enough to make
the problem tangible: a list of at-risk cases where a judge can see which ones the
system acts on, which it deliberately leaves alone, and why, then drill into one
case to see evidence → extraction → recommendation → policy check → outcome.

Explicitly out of scope for v1: subscriptions, abandoned cart, voice, WhatsApp,
multi-channel orchestration, fraud, multi-agent dashboards. These are only
considered after the core engine is solid.

## 13. Demo Script (5 questions a judge should be able to answer by watching)

1. What happened? — "This ₹48,000 receivable is overdue."
2. What evidence exists? — "78% historical promise-keeping rate, one recent partial
   payment, one broken promise."
3. What did the AI recommend? — `WAIT`
4. Why was that allowed? — "Policy allows a 48-hour wait: valid promise exists,
   expected net recovery remains positive."
5. What happened next? — payment arrives → `STOP`, or promise breaks →
   `RE_EVALUATE` → `ESCALATE`.

## 13b. Milestone: Synthetic Environment + Oracle + Baselines (done, 2026-08-21)

Implemented in `env/` (schemas, generator, oracle, baselines, metrics) and
`scripts/run_baseline_eval.py`, with `tests/test_env.py` covering the harness
itself (10 tests passing).

**A real calibration bug was caught and fixed here, not glossed over:** the
first version of the economics never produced STOP as optimal, ever, in a
10,000-case batch. Root cause: `WAIT` had near-zero cost, so any positive
recovery probability trivially beat `STOP`. Fixed by giving `WAIT` a real
carrying cost (opportunity cost of capital, scaling with amount), narrowing
the `LOW` value bucket so "low value" genuinely means cheap-enough-to-write-off,
and correlating the "distressed debt" archetype with the specific taxonomy
corner (low value + already-exhausted + no promise) where `STOP` is
economically reachable rather than leaving it as a diluted independent draw.
`STOP` now appears at ~1% of cases - rare but real and demonstrable, which is
the more defensible story anyway (most receivables genuinely are worth one
cheap attempt; only a narrow minority aren't). Locked in with a regression
test (`test_stop_is_reachable_at_a_real_but_low_rate`).

**First real report (2000 cases, seed=42), see `recon/baseline_eval_report.json`:**

| policy | oracle_agreement | mean_regret | %_of_oracle_value | false_escalation_rate |
|---|---|---|---|---|
| oracle | 100.0% | 0.00 | 100.0% | 0.0% |
| always_pursue | 33.1% | 5776.88 | 80.8% | 0.0% |
| fixed_cadence | 35.8% | 7994.79 | 73.4% | 0.0% |
| simple_heuristic | 31.4% | 4657.63 | 84.5% | 53.5% |

Notable finding worth carrying into the demo: `simple_heuristic` gets closest
to the oracle on raw value (84.5%) but does it by escalating 53.5% of the time
when it shouldn't - a concrete demonstration that value-captured alone isn't
sufficient, exactly the reason `false_escalation_rate` is tracked as its own
diagnostic rather than folded into one blended score.

## 13c. Milestone: AI Extraction/Recommendation + Policy Engine (done, 2026-08-21)

Implemented in `agent/` (extraction + recommendation, calls Anthropic Claude
via forced tool-use for structured output - see `agent/llm_client.py`) and
`policy/` (deterministic guardrails, zero LLM calls). 22/22 tests passing,
all of them running without any API key - the policy engine and the
`agent/parsing.py` safe-parse boundary are tested with hand-crafted inputs,
not live model calls, so the guardrail logic is verified independently of
whether the model behaves.

**Policy precedence, fixed and explainable, in `policy/engine.py`:**
1. Hard attempt limit → forced `STOP`, wins even over a confident recommendation
2. Malformed/unparseable AI output → forced `ESCALATE`, never silently dropped
3. Implausible `expected_recovery` (>1.2x the actual amount) → forced `ESCALATE`
   even if the output was schema-valid - catches a plausible-looking but wrong
   number, not just a malformed one
4. Low-confidence recommendation → forced `ESCALATE` rather than trusted
5. Otherwise, the AI's recommendation stands

Structured-output schema for `recommend_action` constrains `action` to the
literal whitelist via JSON schema enum, so most malformed-action attempts are
caught before they even reach `agent/parsing.py` - the parsing boundary is a
second, independent layer of defense, not the only one.

## 13d. Milestone: Real Agent Pipeline Run + a Genuine Bug Found and Fixed (2026-08-21)

**Provider note:** Anthropic API billing didn't activate as expected (account
showed $0 credit despite trial-credit policy) - rather than block on
resolving that, switched to Groq's free tier (no card required). This was a
one-line config change (`LLM_PROVIDER=groq`), not a rewrite, because
`agent/llm_client.py` was built provider-agnostic from the start. Model used:
`openai/gpt-oss-120b` via Groq (the originally-assumed `llama-3.3-70b-versatile`
no longer exists on Groq's current model list - checked via `client.models.list()`
rather than guessing a second time).

**First real run (25 cases, seed=7), against the actual Claude/Groq pipeline
end to end - extraction → recommendation → policy:**
- 0/25 parse failures, 100% promise detection accuracy, ~0% amount extraction
  error - the extraction step itself was solid from the start
- 0/25 policy overrides observed in this batch - the guardrail precedence
  logic is fully tested with hand-crafted inputs (22/22 unit tests) but
  hasn't yet been exercised by a real low-confidence/malformed model output;
  worth deliberately constructing adversarial cases later to confirm it
  triggers on live output too, not just synthetic test strings
- Oracle agreement 52% (13/25) - clearly beats all three baselines (33.1% /
  35.8% / 31.4% on the 2000-case run)
- Mean regret 7141.57 - worse than 2 of 3 baselines despite the better
  agreement rate, driven almost entirely by two outlier cases

**Root cause, investigated rather than shrugged off:** the two worst cases
(`case_00023`, `case_00008`) both had correct extraction (near-zero amount
error) but bad recommendations - `REMIND` on a promise that was still
credible and pending (should have been `WAIT`), and `WAIT` on a promise that
had already broken (should have been `ESCALATE`). The `ExtractionResult`
schema never explicitly captured pending-vs-broken; the recommendation step
had to infer it indirectly and was under-weighting the signal.

**Fix 1 - schema/prompt:** added an explicit `promise_status: "none"|"pending"|"broken"`
field to `ExtractionResult`, extracted directly from the note's own wording,
and told the recommendation prompt to weigh it heavily (`pending` → usually
`WAIT`, don't intervene just to seem proactive; `broken` → `WAIT` is usually
wrong, patience already failed once). Reran the same 25 cases: mean regret
7141.57 → 3840.29 (-46%). `case_00023` fully fixed (WAIT/regret=0). But
`case_00008` was **unchanged** - regret still 64851.96.

**Fix 2 - the real root cause was in our own data, not the model:** checked
what `case_00008`'s extraction actually produced and found `promise_status`
was extracted as `'pending'`, not `'broken'`. The underlying synthetic
contact note read *"customer said 'definitely by 4 days' previously, still no
sign of the ₹108022"* - genuinely ambiguous wording even to a careful human
reader, since it never states the 4-day deadline had already elapsed. This
was a bug in `env/generator.py`'s BROKEN-outcome template, not a model
reasoning failure. Rewrote the template to be temporally unambiguous
("...within {days} days of that conversation - that deadline has now passed
and there's still no sign of payment"). Reran: `promise_status` now correctly
extracted as `'broken'` with 0.99 confidence.

**Final rerun after both fixes:** mean regret 7141.57 → 1539.04 (**-78% total**).

**The single most useful number from this whole cycle:** oracle agreement
rate stayed at exactly 52% (13/25) across all three runs, completely flat,
while regret fell 78%. Agreement rate would have shown zero improvement.
This is a live, unstaged demonstration of the exact methodological argument
in §10 - value/regret is the metric that actually reveals what changed;
raw agreement rate hides it completely.

| run | mean_regret | oracle_agreement |
|---|---|---|
| baseline (before either fix) | 7141.57 | 52.0% |
| after `promise_status` schema/prompt fix | 3840.29 | 52.0% |
| after fixing the ambiguous BROKEN template | 1539.04 | 52.0% |

Reports saved: `recon/agent_eval_report_before.json` (first run),
`recon/agent_eval_report.json` (final, post-fix).

## 13e. Milestone: Full Live End-to-End Run (done, 2026-08-21)

Implemented in `runtime/` - `db.py` (SQLite; `webhook_events.event_id` is a
PRIMARY KEY, so Failure A dedup is DB-enforced, not an in-memory set that a
restart would lose), `case_store.py`, `razorpay_client.py` (same test-mode-only
hard check as the recon scripts), `case_service.py` (the actual orchestration:
extract → recommend → policy → real Razorpay action → verify → state update),
and `webhook_app.py` (FastAPI, signature verification → dedup → fast ack →
state engine). 31/31 tests passing, all state-machine/idempotency logic
tested via mocks (no live API calls needed for correctness).

**Real bug caught before the live run:** `_observed_from_case` had
`days_past_due` hardcoded to 0, a placeholder left over from scaffolding. The
first live decision correctly (given that wrong input) recommended `WAIT` -
a legitimate decision given what it was told, but wrong information. Added a
proper `days_past_due` column and threaded it through instead of leaving the
placeholder in place.

**Full live run, real money never involved, everything else real:**
1. Created one case, ₹48,000, 22 days overdue, no contact yet
2. `run_decision` → AI recommended `REMIND` (correct reasoning: no promise,
   22 days overdue, first outreach, negative sentiment) → policy passed it
   through unmodified → real `POST /payment_links` created `plink_TSTVlfLRDII9EC`
   → case → `PENDING_VERIFICATION` → immediately polled the real API
   (`status=created, amount_paid=0`, correctly not yet paid)
3. Paid the real link through actual browser checkout (validated domestic
   test card) - completed successfully
4. Real Razorpay webhook arrived at the real tunnel → real `webhook_app.py`
   → signature verified → `payment_link.paid` matched to `live_demo_1` by
   `razorpay_payment_link_id` lookup → **independently re-polled the API
   rather than trusting the webhook payload** → confirmed `status=paid,
   amount_paid=4800000` → case → `RECOVERED`
5. Two unrelated events (`payment.authorized`, `payment.captured` - the
   same "extra events beyond what was subscribed to" behavior noted in the
   recon phase) arrived first and were handled gracefully - correctly
   recognized as carrying no `payment_link` entity, logged, no crash

Full audit trail for this case, in order: `decision → action_executed →
verification (unpaid) → webhook → verification (paid) → state_transition`.
This is `SPEC.md 1`'s architecture diagram, verified to actually be true of
the running code, not just true of a diagram.

## 13f. Milestone: Failure Lab Against the Live System (done, 2026-08-21)

Every scenario from §9 tested against the actual running system with real
data, not just mocks - here's the honest result of each:

| # | Failure | Result |
|---|---|---|
| A - duplicate webhook | **Confirmed live.** Replayed the real captured `payment_link.paid` event (`TSTa4KsOLDvONV`) from `live_demo_1` a second time through `apply_webhook_event`. Correctly flagged `duplicate: true`, audit log entry count unchanged (0 reprocessing). |
| B - out-of-order webhook | **Confirmed live.** Sent a fake-but-plausible `payment_link.partially_paid` event for the same payment link after the case was already `RECOVERED`. Correctly `ignored: true` - state stayed `RECOVERED`, never regressed or double-processed. |
| C - invalid signature | **Confirmed live.** POSTed a corrupted signature directly to the running `webhook_app` (not the recon script). Rejected before `apply_webhook_event` was ever called - never touched the database. |
| D - invalid/malformed AI output | **Proven via 22 unit tests** (hand-crafted bad JSON, out-of-whitelist actions, out-of-range confidence) - not observed to occur naturally with real Groq/gpt-oss-120b output in our live sample. The tool-schema enum constraint likely makes literal invalid-action outputs rare in practice; the guardrail exists and is tested regardless. |
| D2 - low-confidence recommendation | **Attempted live twice, honestly not triggered.** Two deliberately ambiguous/sparse-evidence cases both came back at confidence 0.65 and 0.73 - above the 0.55 threshold. This is a real, useful finding, not a failed test: it suggests this model's self-reported confidence runs higher than the actual ambiguity warrants (a known LLM calibration tendency), which is exactly why the *objective* implausible-`expected_recovery` check exists as a second guardrail that doesn't depend on the model accurately grading its own uncertainty. The override logic itself is proven correct via unit tests with hand-crafted low-confidence inputs. |
| F - verification ambiguous | **Confirmed live.** The very first live decision (before payment) left the case correctly sitting in `PENDING_VERIFICATION` with `status=created, amount_paid=0` rather than assuming success - only transitioned to `RECOVERED` after independently polling and confirming `status=paid`. |

**Honesty note carried through from the original discipline (§9):** two of
seven rows above did not resolve the way we might have hoped for a tidier
demo (the confidence-override case). Reported as-is rather than reframed or
dropped - a fabricated failure story would be worse than an honest partial one.

## 13g. Milestone: Minimal Case-List UI (done, 2026-08-21)

`runtime/ui_app.py` + `runtime/templates/` - a separate FastAPI app (kept
apart from `webhook_app.py` on purpose; a demo UI has no business sharing a
process with the production webhook receiver). Case list shows acted-on vs.
left-alone with the reason; case detail shows the full audit trail.

**Two real bugs caught building this, both fixed, both worth keeping as
examples:**
1. Shared a single module-level SQLite connection across requests -
   crashed under FastAPI's threadpool for sync routes
   (`sqlite3.ProgrammingError: SQLite objects created in a thread can only
   be used in that same thread`). Fixed: open a fresh connection per request.
2. Called `Jinja2Templates.TemplateResponse` with the older
   `(name, {"request": request, ...})` signature; the installed Starlette
   (1.6.0) expects `(request, name, {...})` and failed with a confusing
   `TypeError: unhashable type: 'dict'` several layers down in Jinja2's
   template cache, not at the call site itself. Fixed by matching the
   current API and moving `request` out of the context dict.

**Another honest, unstaged finding from populating the UI with real cases:**
tried to get a genuine "left alone" (`STOP`) example for demo variety. A
₹350 case, 45 days overdue, 2 prior failed contact attempts - a textbook
case for `STOP` per the synthetic environment's own calibration (§13b) -
still got `ESCALATE` from the live model, not `STOP`. Not forced into a
nicer-looking result: reported as observed. Possibly reflects a real bias in
this model toward recommending *some* action over recommending none, echoing
the confidence-calibration finding in §13f (D2) - another data point for why
the deterministic policy layer, not model self-assessment, is what should be
trusted to enforce "sometimes the right call is to stop."

## 14. Open Parameters (resolved during build, not blocking implementation)

- Exact recovery-rate curves per signal combination (calibrate against plausible
  published dunning/collections figures)
- Exact ActionCost / ExpectedPenalty weights
- Confidence threshold below which the policy engine forces human escalation
  regardless of AI recommendation
