"""Learned playbooks, every version (docs/LLD.md §7).

GET /api/{tenant}/playbooks -> list[PlaybookOut], newest first
"""

from fastapi import APIRouter, Depends

from argus_backend import case_mapper
from argus_backend.access_guard import tenant_access
from argus_backend.api_models import PlaybookOut
from argus_soc import graph

router = APIRouter(prefix="/api/{tenant}")


@router.get("/playbooks", response_model=list[PlaybookOut])
async def list_playbooks(tenant: str = Depends(tenant_access)) -> list[PlaybookOut]:
    playbooks = [case_mapper.to_playbook(p) for p in await graph.list_playbooks(tenant)]
    return sorted(playbooks, key=lambda p: (p.created_at is not None, p.created_at), reverse=True)
