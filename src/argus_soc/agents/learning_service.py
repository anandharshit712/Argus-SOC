"""Learning from analyst feedback (docs/LLD.md §6.7).

The API calls `on_feedback` right after `record_feedback` (which already sets the decision
outcome and the IOC verdicts). Only a `benign` verdict teaches anything new: once enough
closed cases with the same category and IOCs were marked benign, the next version of an
auto-close playbook is written, LEARNED_FROM this feedback, and the IOCs get the analyst's
note as their owner. Triage then closes the next matching alert itself.
"""

from argus_soc import graph
from argus_soc.core.logging_setup import get_logger
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_schema import FeedbackVerdict, PlaybookAction


async def on_feedback(tenant: str, case_id: int, feedback_id: str) -> str | None:
    """Returns "<playbook name> v<version>" when a playbook version was created, else None."""
    log = get_logger(__name__, tenant=tenant, case_id=case_id)
    case = await graph.get_case(tenant, case_id)
    feedback = next((f for f in (case or {}).get("feedback", []) if f["id"] == feedback_id), None)
    if feedback is None or feedback["verdict"] != FeedbackVerdict.BENIGN or not case["iocs"]:
        return None

    # Benign closed cases with the same pattern (this one included, once the API closed it).
    benign = 0
    for past in await graph.recall(tenant, ioc=case["iocs"]):
        if past["verdict"] == FeedbackVerdict.BENIGN:
            other = (
                case
                if past["case_id"] == case_id
                else await graph.get_case(tenant, past["case_id"])
            )
            benign += other is not None and other["category"] == case["category"]
    if benign < get_settings().playbook_min_feedback:
        log.info("benign pattern seen %s times; no playbook yet", benign)
        return None

    playbook = await graph.create_playbook_version(
        tenant,
        feedback_id,
        {"category": case["category"], "ioc_in": sorted(case["iocs"])},
        PlaybookAction.AUTO_CLOSE,
    )
    if feedback["note"]:
        for ioc in case["iocs"]:
            await graph.set_ioc_fact(tenant, ioc, "owner", feedback["note"])
    name = f"{playbook['name']} v{playbook['version']}"
    log.info("learned playbook %s", name)
    return name
