"""Read-only graph tools as an MCP server, for the Investigator's deep dive (docs/LLD.md
§4.7, §6.9). This is the Track 01 "MCP tool selection" piece: the LLM sees these tools'
names, one-line descriptions and argument schemas and picks which to call.

    python -m argus_soc.graph.mcp_server        # stdio; the agents process starts it

Rules:
- Only the six read functions are exposed; no write is reachable through MCP.
- Every tool takes `tenant` first and passes it through unchanged. The client (A's
  graph_tool_client) sets it from code and hides it from the LLM; an unknown tenant fails.
- Calls go through `argus_soc.graph`, so ARGUS_GRAPH_BACKEND=stub works here too.
- Results are JSON text cut to 4 000 characters.
- stdout carries the MCP protocol, so logs go to stderr.
"""

import json
import logging
import sys
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from argus_soc import graph
from argus_soc.core.logging_setup import JsonFormatter
from argus_soc.graph.algorithm_queries import MAX_HOPS_LIMIT

RESULT_MAX_CHARS = 4000
TRUNCATED = " ...[truncated]"
READ_TOOLS = (
    "blast_radius",
    "paths_to_crown_jewels",
    "rank_hosts",
    "recall",
    "linked_alerts",
    "entity_facts",
)

Tenant = Annotated[str, Field(description="Tenant id, set by the caller")]
Names = Annotated[list[str], Field(description="Names to look up; may be empty")]
OneOrMany = Annotated[str | list[str] | None, Field(description="One value or a list")]

server = FastMCP("argus-graph")


def _result(value: Any) -> str:
    """Plain Python result -> JSON text, at most RESULT_MAX_CHARS characters."""
    text = json.dumps(value, default=list, ensure_ascii=False)
    if len(text) <= RESULT_MAX_CHARS:
        return text
    return text[: RESULT_MAX_CHARS - len(TRUNCATED)] + TRUNCATED


# Each tool's docstring is the one-line description the LLM chooses from.


@server.tool()
async def blast_radius(tenant: Tenant, ioc: Annotated[str, Field(description="IOC value")]) -> str:
    """Hosts hit by alerts involving an IOC, their accounts and where those accounts log in (Q1)."""
    return _result(await graph.blast_radius(tenant, ioc))


@server.tool()
async def paths_to_crown_jewels(
    tenant: Tenant,
    host: Annotated[str, Field(description="Start host name")],
    max_hops: Annotated[int, Field(ge=1, le=MAX_HOPS_LIMIT, description="Longest path")] = 6,
) -> str:
    """Shortest attack paths from a host to crown-jewel hosts, at most 3 (Q2)."""
    return _result(await graph.paths_to_crown_jewels(tenant, host, max_hops))


@server.tool()
async def rank_hosts(tenant: Tenant, case_id: Annotated[int, Field(description="Case id")]) -> str:
    """A case's hosts ranked by betweenness x criticality; the first is the one to isolate (Q3)."""
    return _result(await graph.rank_hosts(tenant, case_id))


@server.tool()
async def recall(
    tenant: Tenant, ioc: OneOrMany = None, host: OneOrMany = None, user: OneOrMany = None
) -> str:
    """Closed past cases with these IOCs, hosts or users, with verdict and analyst note (Q4)."""
    return _result(await graph.recall(tenant, ioc=ioc, host=host, user=user))


@server.tool()
async def linked_alerts(
    tenant: Tenant,
    incident_id: Annotated[str, Field(description="Talos incident id, e.g. inc-7f3a")],
    window_hours: Annotated[int, Field(ge=0, le=720, description="Time window")] = 24,
) -> str:
    """Other open alerts sharing an IOC or a user with this alert in the time window (Q5)."""
    return _result(await graph.linked_alerts(tenant, incident_id, window_hours))


@server.tool()
async def entity_facts(tenant: Tenant, hosts: Names, users: Names, iocs: Names) -> str:
    """What the graph remembers about hosts, users and IOCs (targeted, suspected, verdict)."""
    return _result(await graph.entity_facts(tenant, hosts, users, iocs))


def main() -> None:
    handler = logging.StreamHandler(sys.stderr)  # never stdout: that is the MCP channel
    handler.setFormatter(JsonFormatter("mcp_server"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
