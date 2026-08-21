# Recovery Decision Engine

Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)

Merchants usually know when revenue is at risk. The harder problem is deciding
whether to intervene, what intervention is actually justified, and when to stop.
This project is a decision layer for that problem, not another retry/notification
bot — an AI-assisted engine that reasons over incomplete, sometimes conflicting
evidence about a recovery opportunity, then passes its recommendation through a
deterministic policy layer before any action is taken. The AI never moves money
directly.

First workflow: promise-to-pay recovery on overdue receivables.

See [SPEC.md](SPEC.md) for the full system specification — entities, action space,
state machine, evaluation methodology (oracle + baselines + regret), failure lab,
and Razorpay integration scope.

## Status

Currently validating the Razorpay test-mode API surface before finalizing the
agent's action/tool contract. Implementation has not started yet.
