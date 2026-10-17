"""The analyst's verdict on a case (docs/LLD.md §7, same steps as tests/e2e give_feedback).

1. The case must exist; approve / reject only while it is awaiting approval; benign also on a
   closed or auto-closed case (so a wrong auto-close can be corrected).
2. `record_feedback` stores it and runs the decision's simulated actions on approve (rule 10).
3. A case that was awaiting approval is closed.
4. `learning_service.on_feedback` may learn a playbook version from a benign verdict.
"""

from dataclasses import dataclass

from argus_soc import graph
from argus_soc.agents import learning_service
from argus_soc.core.logging_setup import get_logger
from argus_soc.graph.graph_schema import CaseStatus, FeedbackVerdict

_CLOSED = {CaseStatus.CLOSED, CaseStatus.AUTO_CLOSED}


class CaseNotFound(Exception):
    pass


class FeedbackConflict(Exception):
    """The case is not in a state that takes this verdict (HTTP 409)."""


@dataclass(frozen=True)
class FeedbackResult:
    feedback_id: str
    playbook_created: str | None


def check_verdict_allowed(status: str, verdict: str) -> None:
    """Raise FeedbackConflict when `verdict` can't be given on a case in `status`."""
    awaiting = status == CaseStatus.AWAITING_APPROVAL
    if verdict == FeedbackVerdict.BENIGN:
        if not (awaiting or status in _CLOSED):
            raise FeedbackConflict(
                "A case can be marked benign once it is awaiting approval or closed"
            )
    elif not awaiting:
        raise FeedbackConflict("This case is not awaiting approval")


async def give_feedback(
    tenant: str, case_id: int, verdict: str, note: str, analyst: str
) -> FeedbackResult:
    log = get_logger(__name__, tenant=tenant, case_id=case_id)
    case = await graph.get_case(tenant, case_id)
    if case is None:
        raise CaseNotFound(case_id)
    check_verdict_allowed(case["status"], verdict)

    feedback_id = await graph.record_feedback(tenant, case_id, verdict, note, analyst)
    if case["status"] == CaseStatus.AWAITING_APPROVAL:
        await graph.set_case_status(tenant, case_id, CaseStatus.CLOSED)
    playbook = await learning_service.on_feedback(tenant, case_id, feedback_id)
    log.info("feedback %s recorded by %s; playbook created: %s", verdict, analyst, playbook)
    return FeedbackResult(feedback_id=feedback_id, playbook_created=playbook)
