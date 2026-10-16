"""Cases: the queue, one case in full, and the analyst's feedback (docs/LLD.md §7).

GET  /api/{tenant}/cases?status=&limit=        -> list[CaseSummary]
GET  /api/{tenant}/cases/{case_id}             -> CaseDetail
POST /api/{tenant}/cases/{case_id}/feedback    -> FeedbackOut
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from argus_backend import case_mapper, feedback_service
from argus_backend.access_guard import current_user, tenant_access
from argus_backend.api_models import CaseDetail, CaseSummary, FeedbackIn, FeedbackOut
from argus_backend.api_settings import DemoUser
from argus_soc import graph
from argus_soc.graph.graph_schema import CaseStatus

router = APIRouter(prefix="/api/{tenant}")


@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(
    tenant: str = Depends(tenant_access),
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[CaseSummary]:
    cases = await graph.list_cases(tenant, str(status_filter) if status_filter else None, limit)
    sources = case_mapper.source_cases(await graph.list_playbooks(tenant))
    return [case_mapper.to_summary(c, sources) for c in cases]


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def get_case(case_id: int, tenant: str = Depends(tenant_access)) -> CaseDetail:
    case = await graph.get_case(tenant, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown case")
    sources = case_mapper.source_cases(await graph.list_playbooks(tenant))
    return case_mapper.to_detail(case, sources)


@router.post("/cases/{case_id}/feedback", response_model=FeedbackOut)
async def give_feedback(
    case_id: int,
    body: FeedbackIn,
    tenant: str = Depends(tenant_access),
    user: DemoUser = Depends(current_user),
) -> FeedbackOut:
    try:
        result = await feedback_service.give_feedback(
            tenant, case_id, body.verdict, body.note.strip(), analyst=user.username
        )
    except feedback_service.CaseNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown case") from None
    except feedback_service.FeedbackConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return FeedbackOut(feedback_id=result.feedback_id, playbook_created=result.playbook_created)
