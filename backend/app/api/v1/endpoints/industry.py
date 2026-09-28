from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Any, List, Optional
from ....schemas.industry import (
    IndustryRequirementResponse,
    RoleSummaryResponse,
    RoleComparisonResponse,
    CustomRoleRequest,
    CustomRoleResponse,
    RetrieveRequest,
    RetrieveResponse,
    IndustryIntelligenceResponse,
    DemandProviderInfo,
    LabourMarketSignalResponse,
    LabourMarketRefreshRequest,
    LabourMarketRefreshResponse,
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
    result = await retrieval_service.retrieve(payload.role, payload.query, payload.top_k, location=payload.location)
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
            "trend": r.get("trend"),
            "freshness": r.get("freshness"),
            "data_origin": r.get("data_origin"),
            "location": r.get("location"),
            "collected_at": r.get("collected_at"),
            "last_updated": r.get("last_updated"),
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
@router.get("/intelligence", response_model=IndustryIntelligenceResponse)
def get_role_intelligence(
    role: str = Query(..., description="Role name e.g., Software Engineer"),
    location: Optional[str] = Query(None, description="Optional location label e.g., Bengaluru; omit for global"),
    country: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    include_dynamics: bool = Query(True),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Role + location industry intelligence view over baseline + dynamic overlays."""
    from ....services import industry_intelligence as _intel

    loc: Any = {"country": country, "region": region, "city": city} if any([country, region, city]) else location
    view = _intel.build_role_intelligence(role, location=loc, include_dynamics=include_dynamics)
    return {
        "role": view["role"],
        "location": view["location"],
        "location_match": view.get("location_match", "global"),
        "last_updated": view.get("last_updated"),
        "skills": [
            {
                "id": str(s.get("id", "")),
                "role": s.get("role", view["role"]),
                "skill": s.get("skill", ""),
                "skill_slug": s.get("skill_slug"),
                "skill_category": s.get("skill_category", "General"),
                "required_level": float(s.get("required_level", 0.75)),
                "importance": float(s.get("importance", 0.5)),
                "demand": float(s.get("demand", 0.5)),
                "interview_relevance": float(s.get("interview_relevance", 0.5)),
                "industry_confidence": float(s.get("industry_confidence", 0.85)),
                "trend": s.get("trend"),
                "freshness": s.get("freshness"),
                "source": s.get("source", ""),
                "source_url": s.get("source_url"),
                "evidence_context": s.get("evidence_context", ""),
                "data_origin": s.get("data_origin"),
                "data_origins": s.get("data_origins"),
                "location": s.get("location"),
                "location_match": s.get("location_match"),
                "mapping_status": s.get("mapping_status"),
                "source_concept": s.get("source_concept"),
                "canonical_mapping": s.get("canonical_mapping", s.get("skill")),
                "collected_at": s.get("collected_at"),
                "last_updated": s.get("last_updated"),
                "published_at": s.get("published_at"),
                "retrieved_at": s.get("retrieved_at"),
            }
            for s in view.get("skills", [])
        ],
        "counts": view.get("counts", {}),
        "data_origins": view.get("data_origins", []),
        "note": view.get("note", ""),
    }


@router.get("/providers", response_model=List[DemandProviderInfo])
def list_demand_providers(current_user: CurrentUser = Depends(get_current_user)):
    """List registered industry-demand providers (pluggable; demo seed by default)."""
    from ....services import industry_intelligence as _intel

    return _intel.list_providers()


@router.get("/labour-market/signals", response_model=List[LabourMarketSignalResponse])
def get_labour_market_signals(
    role: Optional[str] = Query(None, description="Canonical role, e.g. Software Engineer"),
    skill: Optional[str] = Query(None, description="Canonical skill or raw source concept"),
    country: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="ISO date lower bound (period_start)"),
    end_date: Optional[str] = Query(None, description="ISO date upper bound (period_start)"),
    provider_id: Optional[str] = Query(None),
    include_raw_concepts: bool = Query(False, description="Include unmapped source concepts"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Read aggregated labour-market demand signals with full provenance.

    Returns derived measurements (demand/skill_share/trend/confidence) beside
    the raw counts they were computed from. Unmapped concepts are excluded
    unless include_raw_concepts=true. Demo-origin rows are synthetic and are
    never labelled live.
    """
    from ....services import labour_market_service as _lm

    return _lm.get_demand_signals(
        role=role, skill=skill, country=country, region=region, city=city,
        start_date=start_date, end_date=end_date, provider_id=provider_id,
        include_raw_concepts=include_raw_concepts,
    )


@router.post("/labour-market/refresh", response_model=LabourMarketRefreshResponse)
def refresh_labour_market_signals(
    payload: LabourMarketRefreshRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Authenticated deterministic refresh of labour-market aggregates.

    Validates the provider id, fetches that provider's postings (demo provider
    by default — synthetic, never live), and re-aggregates idempotently:
    re-running with identical input yields identical signals. No unauthenticated
    access; no raw posting bodies are returned.
    """
    from ....services import labour_market_service as _lm

    provider = _lm.get_posting_provider(payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider_id: {payload.provider_id}")
    location = None
    if any([payload.country, payload.region, payload.city]):
        location = {"country": payload.country, "region": payload.region, "city": payload.city}
    try:
        raw = provider.fetch_postings(payload.role, location, payload.start_date, payload.end_date)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider fetch failed: {str(e)[:200]}")
    result = _lm.refresh_demand_signals(provider=provider, postings=raw)
    return {"provider_id": provider.provider_id, "ingested": result["ingested"], "signals": result["signals"]}
