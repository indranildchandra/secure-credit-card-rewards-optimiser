"""End-to-end smoke test that ACTUALLY runs the agent (never skipped).

The agent-level evals in ``evals/`` need a live Ollama and are skipped offline,
so nothing in CI proves the ADK wiring — agent -> tool dispatch -> real tool
execution -> result back into the turn -> final answer — actually works. This
test closes that gap with a *scripted* model (no network, no Ollama): it forces
one real tool call and asserts the tool's real output (read from the shipped
config) flows back into the final response.

It does NOT exercise a real LLM's tool-calling judgement (no offline test can) —
it proves the plumbing the demo depends on is intact.
"""

import asyncio
import json

from google.adk.agents import Agent
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from tools.card_tools import find_cards_for_category


def _has_tool_result(llm_request) -> bool:
    for content in llm_request.contents or []:
        for part in content.parts or []:
            if getattr(part, "function_response", None) is not None:
                return True
    return False


def _tool_result_text(llm_request) -> str:
    for content in llm_request.contents or []:
        for part in content.parts or []:
            fr = getattr(part, "function_response", None)
            if fr is not None:
                return json.dumps(fr.response, default=str)
    return ""


class _ScriptedLlm(BaseLlm):
    """Stateless fake model: emit a real tool call, then echo the tool result.

    Turn 1 (no tool result yet) -> a FunctionCall to find_cards_for_category.
    Turn 2 (tool result present) -> final text embedding the tool's output, so
    the assertion proves the real tool ran with the real config.
    """

    async def generate_content_async(self, llm_request, stream=False):
        if _has_tool_result(llm_request):
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text="The Winner (from tool): "
                            + _tool_result_text(llm_request)
                        )
                    ],
                )
            )
        else:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="find_cards_for_category",
                                args={"merchant_or_category": "Amazon", "amount": 4000},
                            )
                        )
                    ],
                )
            )


def _run(prompt: str) -> str:
    agent = Agent(
        name="smoke",
        model=_ScriptedLlm(model="scripted-fake"),
        instruction="Route the transaction using the card tools.",
        tools=[find_cards_for_category],
    )
    runner = InMemoryRunner(agent=agent, app_name="smoke")
    asyncio.run(
        runner.session_service.create_session(
            app_name="smoke", user_id="u", session_id="s"
        )
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    out = []
    for event in runner.run(user_id="u", session_id="s", new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            out.append("".join(p.text or "" for p in event.content.parts))
    return "\n".join(o for o in out if o).strip()


def test_agent_end_to_end_tool_dispatch():
    # Full ADK loop with a scripted model: the real find_cards_for_category runs
    # against the shipped config and its output (Amazon -> ICICI AmazonPay)
    # reaches the final answer. Proves the wiring the live demo relies on.
    answer = _run("I am spending Rs.4,000 on Amazon. Which card?")
    assert "ICICI AmazonPay" in answer
