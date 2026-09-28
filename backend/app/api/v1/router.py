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
from .endpoints.institutions import router as institutions_router
from .endpoints.institutions import course_router as institution_courses_router
from .endpoints.institutions import trainer_router as institution_trainers_router
from .endpoints.cohorts import router as cohorts_router
from .endpoints.cohorts import course_cohort_router as course_cohorts_router
from .endpoints.course_alignment import router as course_alignment_router
from .endpoints.district_training import router as district_training_router
from .endpoints.training_priorities import router as training_priorities_router
from .endpoints.curriculum_proposals import router as curriculum_proposals_router
from .endpoints.trainer_development import router as trainer_development_router
from .endpoints.capacity_planning import router as capacity_planning_router
from .endpoints.proposal_reviews import router as proposal_reviews_router
from .endpoints.outcome_feedback import router as outcome_feedback_router
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
api_router.include_router(institutions_router)  # P0#2: institutions & training supply
api_router.include_router(institution_courses_router)  # P0#2: courses & curriculum
api_router.include_router(institution_trainers_router)  # P0#2: trainers & skills
api_router.include_router(cohorts_router)  # P0#3: cohorts & skill supply
api_router.include_router(course_cohorts_router)  # P0#3: course cohort views
api_router.include_router(course_alignment_router)  # P0#4: course/industry alignment
api_router.include_router(district_training_router)  # P0#5: district training intelligence
api_router.include_router(training_priorities_router)  # P1.1: training priority engine
api_router.include_router(curriculum_proposals_router)  # P1.2: curriculum change proposals
api_router.include_router(trainer_development_router)  # P1.3: trainer development signals
api_router.include_router(capacity_planning_router)  # P1.4: capacity planning signals
api_router.include_router(proposal_reviews_router)  # P1.5: human review / approval
api_router.include_router(outcome_feedback_router)  # P1.6: outcome feedback loop
api_router.include_router(outcomes_router)  # Person 2: applications, feedback, placements
api_router.include_router(requirements_router)  # Person 2: requirement detail/skills
