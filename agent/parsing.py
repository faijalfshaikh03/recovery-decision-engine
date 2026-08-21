"""
The boundary between "text an LLM produced" and "something the policy engine
is allowed to reason about." Nothing past this point is trusted just because
it parsed as JSON - Pydantic's Action enum is what actually rejects an
out-of-whitelist action like "REFUND_CUSTOMER" (see SPEC.md Failure E).
"""

import json
from typing import Union

from pydantic import ValidationError

from agent.schemas import ParseFailure, RecommendationResult


def safe_parse_recommendation(raw_text: str) -> Union[RecommendationResult, ParseFailure]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return ParseFailure(raw_output=raw_text, error=f"invalid JSON: {e}")

    try:
        return RecommendationResult.model_validate(data)
    except ValidationError as e:
        return ParseFailure(raw_output=raw_text, error=f"schema validation failed: {e}")
