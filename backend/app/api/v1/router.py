from fastapi import APIRouter
from .endpoints.profile import router as profile_router
from .endpoints.evidence import router as evidence_router
from .endpoints.industry import router as industry_router
from .endpoints.analysis import router as analysis_router
from .endpoints.capability import router as capability_router
from .endpoints.assessment import router as assessment_router
from .endpoints.roadmap import router as roadmap_router
from .endpoints.ai_review_test import router as ai_review_test_router
from .endpoints.mock_interview import router as mock_interview_router
from .endpoints.resume import router as resume_router
from .endpoints.notion import router as notion_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(profile_router)
api_router.include_router(evidence_router)
api_router.include_router(industry_router)
api_router.include_router(analysis_router)
api_router.include_router(capability_router)
api_router.include_router(assessment_router)
api_router.include_router(roadmap_router)
api_router.include_router(resume_router)
api_router.include_router(ai_review_test_router)  # EXPERIMENTAL side feature only
api_router.include_router(mock_interview_router)  # adaptive AI mock interview (evidence source)
api_router.include_router(notion_router, prefix="/integrations/notion")
