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
from .endpoints.resume_builder import router as resume_builder_router
from .endpoints.notion import router as notion_router
from .endpoints.employers import router as employers_router
from .endpoints.outcomes import router as outcomes_router
from .endpoints.outcomes import requirements_router as requirements_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(profile_router)
api_router.include_router(evidence_router)
api_router.include_router(industry_router)
api_router.include_router(analysis_router)
api_router.include_router(capability_router)
api_router.include_router(assessment_router)
api_router.include_router(roadmap_router)
api_router.include_router(resume_router)
api_router.include_router(resume_builder_router)
api_router.include_router(ai_review_test_router)  # EXPERIMENTAL side feature only
api_router.include_router(mock_interview_router)  # adaptive AI mock interview (evidence source)
api_router.include_router(notion_router, prefix="/integrations/notion")
api_router.include_router(employers_router)  # Person 2: employers & hiring requirements
api_router.include_router(outcomes_router)  # Person 2: applications, feedback, placements
api_router.include_router(requirements_router)  # Person 2: requirement detail/skills
