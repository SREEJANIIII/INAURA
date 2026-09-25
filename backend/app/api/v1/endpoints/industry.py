from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List, Optional
from ....schemas.industry import (
    IndustryRequirementResponse,
    RoleSummaryResponse,
    RoleComparisonResponse,
    CustomRoleRequest,
    CustomRoleResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from ....schemas.industry_outcomes import EmergingSkillOut
from ....services import industry_service, retrieval_service
from ....services import industry_outcome_service as outcome_obs
from ....services.industry_roles import list_catalog_roles
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/roles/catalog", response_model=List[RoleSummaryResponse])
def get_roles_catalog(current_user: CurrentUser = Depends(get_current_user)):
    """Return all 11 catalog roles with structured metadata and benchmark sources."""
    return list_catalog_roles()


@router.get("/roles/compare", response_model=RoleComparisonResponse)
def compare_roles_endpoint(
    role_a: str = Query(..., description="First role title, e.g. Frontend Developer"),
    role_b: str = Query(..., description="Second role title, e.g. Full Stack Developer"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Compare required competencies, skill overlap, and transition guidance between two roles."""
    if not role_a or not role_b:
        raise HTTPException(status_code=400, detail="Both role_a and role_b are required")
    return industry_service.compare_two_roles(role_a, role_b)


@router.get("/roles", response_model=List[str])
def get_roles(current_user: CurrentUser = Depends(get_current_user)):
    """Return list of distinct role names available in industry knowledge."""
    return industry_service.list_roles()


@router.get("/requirements", response_model=List[IndustryRequirementResponse])
def get_requirements(
    role: str = Query(..., description="Role name e.g., Software Engineer"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Return normalized, source-attributed requirements for target role."""
    data = industry_service.list_by_role(role)
    return data


@router.post("/custom-role", response_model=CustomRoleResponse)
async def synthesize_custom_role_endpoint(
    payload: CustomRoleRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """RAG-driven requirement synthesis for custom or non-catalog roles."""
    result = await retrieval_service.synthesize_custom_role(payload.role, payload.query)
    return result


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_requirements(
    payload: RetrieveRequest, current_user: CurrentUser = Depends(get_current_user)
):
    """Retrieve relevant industry requirements via vector search or semantic fallback."""
    result = await retrieval_service.retrieve(payload.role, payload.query, payload.top_k)
    items = [
        {
            "id": str(r.get("id", "")),
            "role": r.get("role", payload.role),
            "skill": r.get("skill", ""),
            "skill_category": r.get("skill_category", "General"),
            "required_level": float(r.get("required_level", r.get("importance", 0.75))),
            "importance": float(r.get("importance", 0.5)),
            "demand": float(r.get("demand", 0.5)),
            "interview_relevance": float(r.get("interview_relevance", 0.5)),
            "industry_confidence": float(r.get("industry_confidence", 0.85)),
            "source": r.get("source", "Industry Knowledge"),
            "source_url": r.get("source_url"),
            "source_version": r.get("source_version"),
            "source_occupation": r.get("source_occupation"),
            "source_reference": r.get("source_reference"),
            "mapping_version": r.get("mapping_version"),
            "role_relevance": r.get("role_relevance"),
            "source_concept": r.get("source_concept"),
            "canonical_mapping": r.get("canonical_mapping", r.get("skill")),
            "mapping_rationale": r.get("mapping_rationale"),
            "source_quality": float(r.get("source_quality", 0.85)),
            "evidence_context": r.get("evidence_context", r.get("description", "")),
            "description": r.get("description"),
            "version": r.get("version", "2026.1"),
            "similarity": float(r.get("similarity", 0.0)),
            "evidence_strength": r.get("evidence_strength"),
            "supporting_chunks": r.get("supporting_chunks"),
            "outcome_overlay": r.get("outcome_overlay"),
        }
        for r in result["items"]
    ]
    return {
        "role": result["role"],
        "query": result["query"],
        "count": result["count"],
        "items": items,
        "note": result.get("note", ""),
    }


@router.get("/outcomes/emerging", response_model=List[EmergingSkillOut])
def get_emerging_skills(
    role: str = Query(..., description="Role name e.g., Software Engineer"),
    location: Optional[str] = Query(None, description="Coarse city, e.g. Bengaluru"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Phase 3 derived read model: aggregated employer-observed skills with NO
    curated requirement for this role. Read-only; status is always
    observed_not_required. Never enters gap mathematics or the taxonomy."""
    from ....services.skill_taxonomy import normalize_skill as _canon

    curated = {
        (_canon(str(r.get("skill", "") or "")) or str(r.get("skill", "") or "")).lower()
        for r in industry_service.list_by_role(role)
    }
    return outcome_obs.get_emerging(role, location, curated)
