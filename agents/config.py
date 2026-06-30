import os

from agents.tool_specs import DEFAULT_TOOL, validate_tool

AGENT_STEP_TIMEOUT = os.environ.get("AGENT_STEP_TIMEOUT", "5m")
AGENT_INTENT_TIMEOUT = os.environ.get("AGENT_INTENT_TIMEOUT", "15s")
DEFAULT_AGENT_TOOL = validate_tool(os.environ.get("AGENT_TOOL", DEFAULT_TOOL))
