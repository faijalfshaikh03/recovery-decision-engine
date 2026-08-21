import json
from typing import Union

from pydantic import ValidationError

from agent.llm_client import call_tool
from agent.schemas import ExtractionResult, ParseFailure

EXTRACTION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "promised_date_days_from_now": {"type": ["integer", "null"]},
        "promised_amount": {"type": ["number", "null"]},
        "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "sentiment": {"type": "string"},
        "has_dispute_mention": {"type": "boolean"},
    },
    "required": ["extraction_confidence", "sentiment", "has_dispute_mention"],
}

SYSTEM_PROMPT = (
    "You extract structured facts from a customer contact note for accounts "
    "receivable follow-up. Only report a promised date or amount if the note "
    "genuinely states one - do not invent one if it's absent or ambiguous. "
    "If the note is vague or conflicting, reflect that with a lower "
    "extraction_confidence rather than guessing confidently."
)


def extract_evidence(contact_note: str) -> Union[ExtractionResult, ParseFailure]:
    user_prompt = f'Contact note:\n"""\n{contact_note}\n"""\n\nExtract the promise details, if any.'
    raw = call_tool(
        SYSTEM_PROMPT,
        user_prompt,
        "extract_evidence",
        "Extract structured evidence from a contact note",
        EXTRACTION_TOOL_SCHEMA,
    )
    try:
        data = json.loads(raw)
        return ExtractionResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        return ParseFailure(raw_output=raw, error=str(e))
