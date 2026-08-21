import json
from typing import Union

from agent.llm_client import call_tool
from agent.parsing import safe_parse_recommendation
from agent.schemas import ExtractionResult, ParseFailure, RecommendationResult
from env.schemas import ObservedEvidence

RECOMMENDATION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["WAIT", "REMIND", "ESCALATE", "STOP"]},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "expected_recovery": {"type": "number"},
        "recheck_in_days": {"type": ["integer", "null"]},
    },
    "required": ["action", "reason", "confidence", "expected_recovery"],
}

SYSTEM_PROMPT = (
    "You are the reasoning layer of a revenue-recovery decision system. You "
    "only RECOMMEND an action - a separate deterministic policy engine "
    "decides whether it is actually allowed to happen, so do not assume your "
    "recommendation executes automatically.\n\n"
    "Choose exactly one action:\n"
    "WAIT - hold, a genuine promise exists and is still pending, or patience "
    "is more appropriate than contact right now.\n"
    "REMIND - send a payment link / notification.\n"
    "ESCALATE - hand to a human or a firmer channel.\n"
    "STOP - not economically worth pursuing further.\n\n"
    "expected_recovery must be a realistic number given the amount owed, not "
    "an aspirational one. If evidence is weak, conflicting, or sparse, say so "
    "in `reason` and reflect it with a lower confidence rather than guessing."
)


def recommend_action(
    observed: ObservedEvidence, extraction: Union[ExtractionResult, ParseFailure]
) -> Union[RecommendationResult, ParseFailure]:
    context = {
        "amount": observed.amount,
        "days_past_due": observed.days_past_due,
        "historical_promise_keep_rate": observed.historical_promise_keep_rate,
        "on_time_payment_ratio": observed.on_time_payment_ratio,
        "prior_intervention_count": observed.prior_intervention_count,
        "prior_intervention_outcomes": observed.prior_intervention_outcomes,
        "recent_partial_payment": observed.recent_partial_payment,
        "has_open_dispute": observed.has_open_dispute,
        "extracted_promise": (
            extraction.model_dump() if isinstance(extraction, ExtractionResult) else None
        ),
        "extraction_failed": isinstance(extraction, ParseFailure),
    }
    user_prompt = f"Case context:\n{json.dumps(context, indent=2)}\n\nRecommend an action."
    raw = call_tool(
        SYSTEM_PROMPT,
        user_prompt,
        "recommend_action",
        "Recommend a revenue-recovery action",
        RECOMMENDATION_TOOL_SCHEMA,
    )
    return safe_parse_recommendation(raw)
