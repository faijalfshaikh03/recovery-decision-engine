"""
Evaluation harness. Headline metric is value/regret-based, not raw oracle
agreement (SPEC.md 10) - missing on a high-value case matters more than
missing on a low-value one, and raw agreement rate hides that.
"""

from typing import Callable

import pandas as pd

from env.oracle import oracle_decide, true_ev_of
from env.schemas import Action, Case


PolicyFn = Callable[[Case], "PolicyDecision"]


def evaluate_policy(cases: list[Case], policy_fn: PolicyFn) -> dict:
    rows = []
    for case in cases:
        decision = policy_fn(case)
        oracle_decision = oracle_decide(case)

        policy_ev = true_ev_of(case, decision.action)
        oracle_ev = true_ev_of(case, oracle_decision.action)

        rows.append(
            {
                "case_id": case.case_id,
                "action": decision.action.value,
                "oracle_action": oracle_decision.action.value,
                "agree": decision.action == oracle_decision.action,
                "policy_ev": policy_ev,
                "oracle_ev": oracle_ev,
                "regret": oracle_ev - policy_ev,
                "amount": case.observed.amount,
                "signal_quality": case.category.signal_quality.value,
                "value_bucket": case.category.value_bucket.value,
                "promise_outcome": case.category.promise_outcome.value,
                "intervention_history": case.category.intervention_history.value,
            }
        )

    df = pd.DataFrame(rows)
    total_policy_ev = df["policy_ev"].sum()
    total_oracle_ev = df["oracle_ev"].sum()

    summary = {
        "n_cases": len(df),
        "oracle_agreement_rate": round(df["agree"].mean(), 4),
        "mean_regret": round(df["regret"].mean(), 2),
        "total_policy_ev": round(total_policy_ev, 2),
        "total_oracle_ev": round(total_oracle_ev, 2),
        "pct_of_oracle_value": (
            round(total_policy_ev / total_oracle_ev * 100, 2)
            if total_oracle_ev != 0
            else float("nan")
        ),
        "false_escalation_rate": round(
            ((df["action"] == Action.ESCALATE.value) & (df["oracle_action"] != Action.ESCALATE.value)).mean(),
            4,
        ),
        "unnecessary_intervention_rate": round(
            (
                df["action"].isin([Action.REMIND.value, Action.ESCALATE.value])
                & (df["oracle_action"] == Action.STOP.value)
            ).mean(),
            4,
        ),
    }

    by_signal_quality = (
        df.groupby("signal_quality")[["regret", "agree"]].mean().round(4).to_dict("index")
    )
    by_value_bucket = (
        df.groupby("value_bucket")[["regret", "agree"]].mean().round(4).to_dict("index")
    )

    return {
        "summary": summary,
        "by_signal_quality": by_signal_quality,
        "by_value_bucket": by_value_bucket,
        "raw": df,
    }
