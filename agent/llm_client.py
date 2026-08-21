"""
Thin wrapper around the Anthropic API. Uses forced tool-use for structured
output rather than asking the model to "please output JSON" - this is the
production-correct way to get structured output, not a shortcut.

Model ID is configurable via ANTHROPIC_MODEL since the exact current model
string can drift; this only sets a reasonable default.
"""

import json
import os

from anthropic import Anthropic

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing from environment/.env")
        _client = Anthropic(api_key=api_key)
    return _client


def call_tool(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
) -> str:
    """Returns the tool call's input as a raw JSON string, so callers can run
    it through the same safe-parsing path regardless of whether the JSON came
    from a real model call or a hand-crafted test string."""
    client = get_client()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": input_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    for block in response.content:
        if block.type == "tool_use":
            return json.dumps(block.input)

    raise RuntimeError("model response did not include a tool_use block")
