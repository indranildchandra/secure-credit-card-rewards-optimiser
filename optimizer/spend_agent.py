"""
Spend & analytics feature as a focused sub-agent.

This is the repo's reference example of the "feature = sub-agent" standard (see
AGENTS.md → "Agent architecture"). The spend/cap/fee-waiver/ROI/recall tools are
a cohesive cluster used only on a minority of turns, so instead of loading their
six tool schemas into the root agent on *every* call, they live in a specialist
sub-agent exposed to the root as a single ``AgentTool``. The common "which card?"
path stays lean; this sub-agent's tools are only loaded when it's invoked.

State is preserved: ADK's AgentTool seeds the sub-agent with the parent's session
state and forwards its state deltas back, so the user-scoped ``user:spend_log``
is read and written exactly as if the tools ran on the root.
"""

import os

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from config import MODEL
from tools.spend_tracker import (
    record_spend,
    get_spend_summary,
    get_spend_history,
    check_cap_status,
    check_fee_waiver_status,
    assess_card_value,
)

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "spend_instruction.prompt"
)
with open(_PROMPT_PATH, encoding="utf-8") as _f:
    _INSTRUCTION = _f.read()

spend_agent = Agent(
    name="spend_manager",
    model=MODEL,
    description=(
        "Tracks and analyses the user's spending: record spends, check "
        "caps/thresholds/milestones, fee-waiver progress, card ROI, and recall "
        "recent months' totals."
    ),
    instruction=_INSTRUCTION,
    tools=[
        record_spend,
        get_spend_summary,
        get_spend_history,
        check_cap_status,
        check_fee_waiver_status,
        assess_card_value,
    ],
)

# Exposed to the root optimiser as a single tool.
spend_manager_tool = AgentTool(agent=spend_agent)
