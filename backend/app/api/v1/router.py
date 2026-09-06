from fastapi import APIRouter
from .endpoints.profile import router as profile_router
from .endpoints.evidence import router as evidence_router
from .endpoints.industry import router as industry_router
from .endpoints.analysis import router as analysis_router
from .endpoints.roadmap import router as roadmap_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(profile_router)
api_router.include_router(evidence_router)
api_router.include_router(industry_router)
api_router.include_router(analysis_router)
api_router.include_router(roadmap_router)
