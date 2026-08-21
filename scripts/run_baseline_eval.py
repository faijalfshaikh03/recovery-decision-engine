"""Generates a synthetic batch and reports oracle vs. baseline performance.
This is the harness everything else gets measured against - run it whenever
a real policy exists to compare against these numbers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env.baselines import BASELINES
from env.generator import generate_batch
from env.metrics import evaluate_policy
from env.oracle import oracle_decide

N_CASES = 2000


def main():
    cases = generate_batch(N_CASES, seed=42)
    print(f"Generated {len(cases)} synthetic cases covering the full category taxonomy.\n")

    results = {}
    oracle_result = evaluate_policy(cases, lambda c: oracle_decide(c))
    results["oracle"] = oracle_result["summary"]

    for name, fn in BASELINES.items():
        result = evaluate_policy(cases, fn)
        results[name] = result["summary"]

    print(f"{'policy':<18} {'n':>5} {'oracle_agree%':>14} {'mean_regret':>12} {'%_of_oracle_value':>18}")
    print("-" * 72)
    for name, summary in results.items():
        print(
            f"{name:<18} {summary['n_cases']:>5} "
            f"{summary['oracle_agreement_rate']*100:>13.1f}% "
            f"{summary['mean_regret']:>12.2f} "
            f"{summary['pct_of_oracle_value']:>17.1f}%"
        )

    print("\nDiagnostics (false_escalation_rate / unnecessary_intervention_rate):")
    for name, summary in results.items():
        print(
            f"  {name:<18} false_escalation={summary['false_escalation_rate']*100:.1f}%  "
            f"unnecessary_intervention={summary['unnecessary_intervention_rate']*100:.1f}%"
        )

    out_path = Path(__file__).resolve().parent.parent / "recon" / "baseline_eval_report.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
