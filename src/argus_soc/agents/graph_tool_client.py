"""The Investigator's deep dive (docs/LLD.md §6.9): the LLM picks read-only graph tools.

Track 01's "MCP tool selection": the graph MCP server (graph/mcp_server.py, stdio subprocess)
lists its tools; the LLM sees their names, descriptions and argument schemas and chooses one
call at a time, up to DEEP_DIVE_MAX_CALLS. The calls and results become evidence on the case
and the AgentRun; the decision table never reads them (rule 8).

- **Tenant set by code:** `tenant` is removed from the schemas the LLM sees and put back on
  every call, overwriting any `tenant` the LLM sends.
- **Read-only:** the server exposes only read functions.
- **Bounded and forgiving:** an unknown tool, a tool error, an LLM failure or an MCP failure
  ends the dive; the calls made so far are kept and the case moves on.
"""

import json
import os
import shlex
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

from argus_soc.agents import llm_client
from argus_soc.core.logging_setup import get_logger
from argus_soc.core.settings import get_settings

RESULT_MAX_CHARS = 4000


class ToolChoice(BaseModel):
    done: bool
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


def _server_params() -> StdioServerParameters:
    command, *args = shlex.split(get_settings().mcp_server_command)
    if command in ("python", "python3"):
        command = sys.executable  # the same interpreter and packages as this process
    # The server reads the same settings (graph backend, tenants, FalkorDB host).
    return StdioServerParameters(command=command, args=args, env=dict(os.environ))


def _for_llm(tool: Any) -> dict[str, Any]:
    """A tool as the LLM sees it: no `tenant` argument."""
    schema = json.loads(json.dumps(tool.inputSchema))
    schema.get("properties", {}).pop("tenant", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r != "tenant"]
    return {"name": tool.name, "description": tool.description, "arguments": schema}


async def deep_dive(
    tenant: str, case: dict[str, Any], findings: dict[str, Any]
) -> list[dict[str, Any]]:
    """Up to DEEP_DIVE_MAX_CALLS LLM-chosen graph lookups: [{tool, args, result, why}]."""
    settings = get_settings()
    if not settings.deep_dive_active or llm_client.provider() is None:
        return []
    log = get_logger(__name__, tenant=tenant, case_id=case["id"], agent="investigator")
    calls: list[dict[str, Any]] = []
    try:
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                names = {t.name for t in tools}
                shown = [_for_llm(t) for t in tools]
                for left in range(settings.deep_dive_max_calls, 0, -1):
                    choice = await llm_client.complete(
                        "investigator_deepdive_v1",
                        {
                            "tools": shown,
                            "case_id": str(case["id"]),
                            "status": case["status"],
                            "priority": case["priority"],
                            "category": case["category"] or "",
                            "hosts": llm_client.untrusted(case["hosts"]),
                            "users": llm_client.untrusted(case["users"]),
                            "iocs": case["iocs"],
                            "findings": findings,
                            "summaries": llm_client.untrusted(
                                [a["summary"] for a in case["alerts"]]
                            ),
                            "calls": llm_client.untrusted(calls) if calls else "none yet",
                            "calls_left": str(left),
                        },
                        ToolChoice,
                    )
                    if choice is None or choice.done or choice.tool not in names:
                        break  # no answer, finished, or an unknown tool: never guess
                    args = {k: v for k, v in choice.args.items() if k != "tenant"}
                    result = await session.call_tool(choice.tool, {**args, "tenant": tenant})
                    text = "".join(c.text for c in result.content if c.type == "text")
                    calls.append(
                        {
                            "tool": choice.tool,
                            "args": args,
                            "result": text[:RESULT_MAX_CHARS],
                            "why": choice.reason,
                        }
                    )
                    if result.isError:
                        break
    except Exception:
        log.exception("deep dive ended early after %d calls", len(calls))
    return calls
