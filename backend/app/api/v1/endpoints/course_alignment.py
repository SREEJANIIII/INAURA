"""P0 #4: course / industry alignment endpoint (thin route -> service).

Lives under the industry prefix alongside the labour-market read endpoints,
in its own module so P0 #1 files stay untouched. Responses are aggregate
projections only — no student-level data.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.alignment import CourseAlignmentResponse
from ....services import course_alignment_service as svc

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/course-alignment", response_model=CourseAlignmentResponse)
def get_course_alignment(
    course_id: str = Query(..., description="Course UUID, e.g. from /institutions/{id}/courses"),
    role: str = Query(..., description="Target role, e.g. Software Engineer"),
    cohort_id: Optional[str] = Query(None, description="Single cohort UUID; omit for course-combined supply"),
    country: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="ISO date lower bound on demand period"),
    end_date: Optional[str] = Query(None, description="ISO date upper bound on demand period"),
    provider_id: Optional[str] = Query(None, description="Demand provider, e.g. demo_postings_v1"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deterministic course/industry alignment projection.

    Joins P0 #1 demand, P0 #2 curriculum, and P0 #3 cohort supply on canonical
    skill identity with explicit status axes and provenance. No LLM judgments;
    unmapped concepts are counted and excluded, never fabricated.
    """
    return svc.get_course_alignment(
        course_id=course_id, role=role, cohort_id=cohort_id,
        country=country, region=region, city=city,
        start_date=start_date, end_date=end_date, provider_id=provider_id,
    )
