"""
Runs the real AI extraction -> recommendation -> policy pipeline against a
small batch of synthetic cases (real API calls, so kept small - this is not
the 2000-case pure-simulation harness). Reports extraction accuracy against
hidden ground truth and regret against the oracle, same as run_baseline_eval.

Usage: python scripts/run_agent_eval.py [n_cases]
"""

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agent.extract import extract_evidence
from agent.recommend import recommend_action
from agent.schemas import ExtractionResult, ParseFailure, RecommendationResult
from env.generator import generate_batch
from env.oracle import oracle_decide, true_ev_of
from policy.engine import apply_policy

N_CASES = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def score_extraction(case, extraction) -> dict:
    hidden = case.hidden
    if isinstance(extraction, ParseFailure):
        return {"promise_detection_correct": False, "amount_error_pct": None, "parse_failed": True}

    detected_promise = extraction.promised_amount is not None
    detection_correct = detected_promise == hidden.promise_exists

    amount_error_pct = None
    if hidden.promise_exists and detected_promise and hidden.true_promised_amount:
        amount_error_pct = abs(extraction.promised_amount - hidden.true_promised_amount) / hidden.true_promised_amount

    return {
        "promise_detection_correct": detection_correct,
        "amount_error_pct": amount_error_pct,
        "parse_failed": False,
    }


def main():
    cases = generate_batch(N_CASES, seed=7)
    print(f"Running real agent pipeline on {len(cases)} synthetic cases...\n")

    rows = []
    for i, case in enumerate(cases):
        extraction = extract_evidence(case.observed.contact_note)
        recommendation = recommend_action(case.observed, extraction)
        outcome = apply_policy(case.observed, recommendation)

        oracle_decision = oracle_decide(case)
        oracle_ev = true_ev_of(case, oracle_decision.action)
        policy_ev = true_ev_of(case, outcome.action)

        ext_score = score_extraction(case, extraction)

        row = {
            "case_id": case.case_id,
            "promise_outcome": case.category.promise_outcome.value,
            "extraction_ok": not isinstance(extraction, ParseFailure),
            **ext_score,
            "ai_action": (
                recommendation.action.value
                if isinstance(recommendation, RecommendationResult)
                else "PARSE_FAILURE"
            ),
            "ai_confidence": (
                recommendation.confidence if isinstance(recommendation, RecommendationResult) else None
            ),
            "policy_action": outcome.action.value,
            "was_overridden": outcome.was_overridden,
            "override_reason": outcome.override_reason,
            "oracle_action": oracle_decision.action.value,
            "agree_with_oracle": outcome.action == oracle_decision.action,
            "regret": oracle_ev - policy_ev,
        }
        rows.append(row)
        print(
            f"[{i+1}/{len(cases)}] {case.category.promise_outcome.value:8s} "
            f"ai={row['ai_action']:9s} policy={row['policy_action']:9s} "
            f"oracle={row['oracle_action']:9s} overridden={outcome.was_overridden} "
            f"regret={row['regret']:.0f}"
        )

    n = len(rows)
    n_parse_failures = sum(1 for r in rows if not r["extraction_ok"])
    n_detection_correct = sum(1 for r in rows if r["promise_detection_correct"])
    amount_errors = [r["amount_error_pct"] for r in rows if r["amount_error_pct"] is not None]
    n_overridden = sum(1 for r in rows if r["was_overridden"])
    n_agree_oracle = sum(1 for r in rows if r["agree_with_oracle"])
    mean_regret = sum(r["regret"] for r in rows) / n

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"n_cases: {n}")
    print(f"extraction parse failures: {n_parse_failures}/{n}")
    print(f"promise detection accuracy: {n_detection_correct}/{n} ({n_detection_correct/n*100:.1f}%)")
    if amount_errors:
        print(f"mean promised-amount error: {sum(amount_errors)/len(amount_errors)*100:.1f}%")
    print(f"policy overrode the AI recommendation: {n_overridden}/{n} ({n_overridden/n*100:.1f}%)")
    print(f"final decision matched oracle: {n_agree_oracle}/{n} ({n_agree_oracle/n*100:.1f}%)")
    print(f"mean regret: {mean_regret:.2f}")

    out_path = Path(__file__).resolve().parent.parent / "recon" / "agent_eval_report.json"
    with open(out_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nFull per-case report written to {out_path}")


if __name__ == "__main__":
    main()
