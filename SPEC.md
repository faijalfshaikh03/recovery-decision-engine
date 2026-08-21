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

| # | Failure | Required behavior |
|---|---|---|
| A | Stale state — system thinks invoice unpaid, payment already arrived | Refuse further intervention; re-verify before any action |
| B | Duplicate event — same promise/webhook arrives twice | State transition must be idempotent; no duplicate action |
| C | Conflicting signals — poor history but a fresh partial payment | AI recommendation must surface uncertainty, not silently pick one signal |
| D | Invalid model output — e.g. AI proposes an out-of-whitelist or malformed action | Schema/policy layer rejects it; logged, not executed |
| E | Action succeeds but verification fails/unclear | Move to `PENDING_VERIFICATION`, never straight to `FAILED` or `RECOVERED` |

Each of these should be a reproducible test case with a before/after log — this is
the literal "what broke at 2am, how you got out" material for the README.

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

## 11. Razorpay Integration Scope (v1)

Kept deliberately minimal — the differentiator is the decision layer, not payment-rail
depth. **Status: docs-verified, not yet live-verified** — confirmed against official
Razorpay documentation; actual auth/behavior against a real test account is the next
step (§Recon) before this is finalized.

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

## 14. Open Parameters (resolved during build, not blocking implementation)

- Exact recovery-rate curves per signal combination (calibrate against plausible
  published dunning/collections figures)
- Exact ActionCost / ExpectedPenalty weights
- Confidence threshold below which the policy engine forces human escalation
  regardless of AI recommendation
