"""
Thin, provider-dispatching wrapper for structured (tool-forced) LLM calls.
Set LLM_PROVIDER=anthropic|groq in .env to choose the backend - extract.py
and recommend.py don't know or care which one is active, they just call
call_tool(...) and get back a raw JSON string either way. This is what makes
the provider swap (forced by an Anthropic billing hiccup) a one-line config
change instead of a rewrite.
"""

import json
import os

_anthropic_client = None
_groq_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing from environment/.env")
        _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY missing from environment/.env")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _call_tool_anthropic(system_prompt, user_prompt, tool_name, tool_description, input_schema) -> str:
    client = _get_anthropic_client()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if block.type == "tool_use":
            return json.dumps(block.input)
    raise RuntimeError("model response did not include a tool_use block")


def _call_tool_groq(system_prompt, user_prompt, tool_name, tool_description, input_schema) -> str:
    client = _get_groq_client()
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=1024,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": input_schema,
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    tool_calls = response.choices[0].message.tool_calls or []
    if not tool_calls:
        raise RuntimeError("model response did not include a tool call")
    return tool_calls[0].function.arguments


def call_tool(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
) -> str:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
    if provider == "groq":
        return _call_tool_groq(system_prompt, user_prompt, tool_name, tool_description, input_schema)
    if provider == "anthropic":
        return _call_tool_anthropic(system_prompt, user_prompt, tool_name, tool_description, input_schema)
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider!r} (expected 'anthropic' or 'groq')")
