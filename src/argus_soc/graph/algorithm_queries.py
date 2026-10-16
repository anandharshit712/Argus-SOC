"""Graph-algorithm reads, real FalkorDB versions (docs/LLD.md §4.4, Q2 and Q3).

Both use FalkorDB's built-in algorithms rather than hand-written traversals:
- Q2 uses algo.SPpaths. The LLD's draft used shortestPath(), but FalkorDB only accepts
  shortestPath in WITH/RETURN and only along edge direction, while attack paths here
  go both ways (a user who logs into two hosts links them).
- Q3 uses algo.betweenness on the host network: a host that many paths cross is the
  best single place to cut an attacker off.
"""

from argus_soc.graph.falkor_client import run_read
from argus_soc.graph.graph_schema import CROWN_JEWEL_TAG, Label, Rel

HOST, CASE, ALERT = Label.HOST, Label.CASE, Label.ALERT
MAX_PATHS = 3
MAX_HOPS_LIMIT = 10

_PATHS = f"""
MATCH (src:{HOST} {{hostname: $host}}),
      (dst:{HOST})-[:{Rel.TAGGED}]->(:{Label.ASSET_TAG} {{name: $tag}})
WHERE dst <> src
CALL algo.SPpaths({{sourceNode: src, targetNode: dst,
                    relTypes: ['{Rel.CONNECTS_TO}', '{Rel.LOGGED_INTO}'],
                    relDirection: 'both', maxLen: $max_hops, pathCount: $count}})
YIELD path
RETURN [n IN nodes(path) | coalesce(n.hostname, n.username)] AS names, length(path) AS hops
"""


async def paths_to_crown_jewels(tenant: str, host: str, max_hops: int = 6) -> list[list[str]]:
    """Q2: shortest paths from `host` to hosts tagged crown-jewel over CONNECTS_TO and
    LOGGED_INTO (either direction), as node names. Shortest first, at most 3."""
    if not 1 <= max_hops <= MAX_HOPS_LIMIT:
        raise ValueError(f"max_hops must be 1..{MAX_HOPS_LIMIT}")
    rows = await run_read(
        tenant,
        _PATHS,
        {"host": host, "tag": CROWN_JEWEL_TAG, "max_hops": max_hops, "count": MAX_PATHS},
    )
    ordered = sorted(rows, key=lambda r: (r["hops"], r["names"]))
    unique: list[list[str]] = []
    for row in ordered:
        if row["names"] not in unique:
            unique.append(row["names"])
    return unique[:MAX_PATHS]


_CASE_HOSTS = f"""
MATCH (:{CASE} {{id: $case_id}})-[:{Rel.CONTAINS}]->(:{ALERT})-[:{Rel.ON_HOST}]->(h:{HOST})
RETURN DISTINCT h.hostname AS host, coalesce(h.criticality, 1) AS criticality
"""

_BETWEENNESS = f"""
CALL algo.betweenness({{nodeLabels: ['{HOST}'], relationshipTypes: ['{Rel.CONNECTS_TO}']}})
YIELD node, score
WHERE node.hostname IN $hosts
RETURN node.hostname AS host, score
"""


async def rank_hosts(tenant: str, case_id: int) -> list[tuple[str, float]]:
    """Q3: the case's hosts ranked by (betweenness + 1) x criticality, scaled so the best
    host scores 1.0. The first one is the host the Responder isolates."""
    hosts = await run_read(tenant, _CASE_HOSTS, {"case_id": case_id})
    if not hosts:
        return []
    names = [h["host"] for h in hosts]
    between = {
        r["host"]: r["score"] for r in await run_read(tenant, _BETWEENNESS, {"hosts": names})
    }
    raw = {h["host"]: (between.get(h["host"], 0.0) + 1.0) * h["criticality"] for h in hosts}
    top = max(raw.values())
    ranked = [(host, round(score / top, 2)) for host, score in raw.items()]
    return sorted(ranked, key=lambda r: (-r[1], r[0]))
