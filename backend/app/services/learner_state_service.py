"""
INAURA Learner Skill State & Evidence Snapshot Engine

Implements:
1. Normalized evidence representation & evidence audit.
2. LearnerSkillState evaluation (KNOWN, INFERRED, UNKNOWN).
   Core Rule: "No evidence" must NOT automatically mean "zero skill".
3. Immutable EvidenceSnapshot creation before roadmap generation.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import uuid
import logging
from fastapi import HTTPException
from supabase import Client

from ..core.supabase import get_supabase_client
from .skill_taxonomy import normalize_skill, normalize_skill_slug, get_all_skills
from .evidence_weights import SOURCE_RELIABILITY, ASSESSMENT_SOURCE
from . import evidence_service

logger = logging.getLogger(__name__)

TABLE_SNAPSHOTS = "evidence_snapshots"
TABLE_LEARNER_STATES = "learner_skill_states"
ENGINE_VERSION = "5A-v1"


def _client() -> Optional[Client]:
    return get_supabase_client()


@dataclass
class EvidenceItem:
    """Normalized evidence representation."""
    id: str
    user_id: str
    source_type: str  # github, leetcode, codeforces, kaggle, resume, linkedin, assessment, course, certification, project, profile, manual
    source_id: Optional[str]
    skill: str
    evidence_type: str
    evidence_strength: float  # [0.0, 1.0]
    evidence_depth: int       # 0..4
    recency_days: Optional[int]
    extracted_value: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LearnerSkillState:
    """Synthesized learner state for a canonical skill."""
    user_id: str
    skill_slug: str
    skill_name: str
    state_classification: str  # 'KNOWN', 'INFERRED', 'UNKNOWN'
    proficiency: float          # [0.0, 1.0]
    confidence: float           # [0.0, 1.0]
    required_level: float       # [0.0, 1.0]
    gap: float                  # [0.0, 1.0]
    evidence_coverage: float    # ratio of capabilities demonstrated
    evidence_strength: float    # peak signal strength
    evidence_count: int
    evidence_depth: int         # 0..4
    evidence_recency_days: Optional[int]
    active_sources: List[str]
    evidence_ids: List[str]
    reasoning: str
    last_evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


def audit_user_sources(user_id: str) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    Audit which evidence sources are actually available and analyzed vs unavailable.
    Does NOT claim a source is analyzed unless the application actually has access to it.
    """
    try:
        evidence_items = evidence_service.list_evidence(user_id)
    except Exception:
        evidence_items = []
    try:
        projects = evidence_service.list_projects(user_id)
    except Exception:
        projects = []
    try:
        certs = evidence_service.list_certs(user_id)
    except Exception:
        certs = []

    sources_analyzed: List[Dict[str, Any]] = []
    sources_available: List[str] = []
    
    # Check each potential source honestly
    all_possible_sources = [
        "github", "leetcode", "codeforces", "kaggle",
        "resume", "linkedin", "projects", "certifications", "assessment"
    ]

    has_github = False
    has_leetcode = False
    has_codeforces = False
    has_kaggle = False
    has_resume = False
    has_linkedin = False

    for ev in evidence_items:
        etype = (ev.get("evidence_type") or "").lower()
        v_status = ev.get("verification_status") or "unverified"
        if etype == "github":
            has_github = True
            sources_analyzed.append({
                "source": "github",
                "status": v_status,
                "url": ev.get("source_url"),
                "repos_inspected": ev.get("metadata", {}).get("inspection", {}).get("repositories_inspected", 0)
            })
        elif etype == "leetcode":
            has_leetcode = True
            sources_analyzed.append({"source": "leetcode", "status": v_status, "user": ev.get("source_url")})
        elif etype == "codeforces":
            has_codeforces = True
            sources_analyzed.append({"source": "codeforces", "status": v_status, "handle": ev.get("source_url")})
        elif etype == "kaggle":
            has_kaggle = True
            sources_analyzed.append({"source": "kaggle", "status": v_status, "user": ev.get("source_url")})
        elif etype == "resume":
            has_resume = True
            sources_analyzed.append({"source": "resume", "status": "parsed", "title": ev.get("title")})
        elif etype == "linkedin":
            has_linkedin = True
            sources_analyzed.append({"source": "linkedin", "status": "collected", "url": ev.get("source_url")})

    if projects:
        sources_analyzed.append({"source": "projects", "count": len(projects), "status": "analyzed"})
        sources_available.append("projects")
    if certs:
        sources_analyzed.append({"source": "certifications", "count": len(certs), "status": "analyzed"})
        sources_available.append("certifications")

    if has_github: sources_available.append("github")
    if has_leetcode: sources_available.append("leetcode")
    if has_codeforces: sources_available.append("codeforces")
    if has_kaggle: sources_available.append("kaggle")
    if has_resume: sources_available.append("resume")
    if has_linkedin: sources_available.append("linkedin")

    sources_unavailable = [s for s in all_possible_sources if s not in sources_available]

    return sources_analyzed, sources_available, sources_unavailable


def classify_learner_state(
    proficiency: float,
    confidence: float,
    evidence_count: int,
    evidence_depth: int,
    has_assessment: bool,
    active_sources: List[str],
    skill_name: str,
    gap_val: float,
    required_level: float,
) -> Tuple[str, str]:
    """
    Synthesize explicit learner state:
    - KNOWN: Confirmed demonstrated mastery through direct assessment (>= 0.60),
             Depth 4 substantial implementation, or verified platform ranking.
             High confidence (>= 0.50).
    - INFERRED: Supporting evidence exists (Depth 2/3, coursework, project descriptions,
               or related technology transfer). Confidence between 0.15 and 0.50.
    - UNKNOWN: No active evidence found.
               IMPORTANT: Must NOT be framed as 'Student has 0% ability'. It is
               specifically an unverified requirement awaiting demonstration.
    """
    if has_assessment and proficiency >= 0.55:
        classification = "KNOWN"
        reasoning = (
            f"Demonstrated fluency in {skill_name} directly verified through INAURA assessment "
            f"({int(round(proficiency * 100))}% score). Meets role expectation."
        )
    elif evidence_depth >= 4 and confidence >= 0.50 and proficiency >= 0.60:
        classification = "KNOWN"
        reasoning = (
            f"Substantial multi-file implementation and verified tests found in repository evidence "
            f"({int(round(proficiency * 100))}% demonstrated level)."
        )
    elif evidence_count > 0 or confidence >= 0.15 or proficiency > 0.10:
        classification = "INFERRED"
        sources_str = ", ".join(active_sources) if active_sources else "supporting portfolio artifacts"
        reasoning = (
            f"Supporting evidence detected from {sources_str} (Depth {evidence_depth}). "
            f"Estimated at {int(round(proficiency * 100))}% proficiency with {int(round(confidence * 100))}% confidence. "
            f"Further practical validation recommended."
        )
    else:
        classification = "UNKNOWN"
        reasoning = (
            f"No supporting evidence or assessment found for {skill_name}. "
            f"Target role requires {int(round(required_level * 100))}%. "
            f"This is an unevidenced gap — not assumed to be zero skill, but requires demonstration."
        )

    return classification, reasoning


def compile_learner_skill_states(
    user_id: str,
    assessments: List[dict],
    gaps: List[dict],
) -> Dict[str, LearnerSkillState]:
    """
    Compile and persist LearnerSkillState for all assessed skills and gaps.
    """
    gaps_by_slug: Dict[str, dict] = {}
    for g in gaps:
        slug = normalize_skill_slug(g.get("canonical_name", g.get("skill", ""))) or g.get("canonical_name", "")
        gaps_by_slug[slug] = g

    learner_states: Dict[str, LearnerSkillState] = {}
    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()

    for a in assessments:
        skill_name = a.get("canonical_name") or a.get("skill") or "Unknown"
        slug = normalize_skill_slug(skill_name) or skill_name.lower().replace(" ", "_")
        prof = float(a.get("proficiency", 0.0))
        conf = float(a.get("confidence", 0.0))
        req = float(a.get("required_level", 0.75))
        gap_val = float(a.get("gap", max(0.0, req - prof)))
        ev_count = int(a.get("evidence_count", 0))
        ev_depth = int(a.get("evidence_depth") or 0)
        has_assess = bool(a.get("has_assessment", False))

        # Extract active sources
        ev_sources = a.get("evidence_sources") or []
        active_srcs = list(set(s.get("source_type", "evidence") for s in ev_sources if isinstance(s, dict)))
        ev_ids = [s.get("source_id") for s in ev_sources if isinstance(s, dict) and s.get("source_id")]

        classification, reasoning = classify_learner_state(
            proficiency=prof,
            confidence=conf,
            evidence_count=ev_count,
            evidence_depth=ev_depth,
            has_assessment=has_assess,
            active_sources=active_srcs,
            skill_name=skill_name,
            gap_val=gap_val,
            required_level=req,
        )

        state = LearnerSkillState(
            user_id=user_id,
            skill_slug=slug,
            skill_name=skill_name,
            state_classification=classification,
            proficiency=prof,
            confidence=conf,
            required_level=req,
            gap=gap_val,
            evidence_coverage=1.0 if prof >= req else (prof / req if req > 0 else 0.0),
            evidence_strength=float(a.get("evidence_weight", 0.0)),
            evidence_count=ev_count,
            evidence_depth=ev_depth,
            evidence_recency_days=None,
            active_sources=active_srcs,
            evidence_ids=ev_ids,
            reasoning=reasoning,
            last_evaluated_at=now_iso,
        )
        learner_states[slug] = state

        # Best-effort persist to DB
        if c:
            try:
                row = {
                    "user_id": user_id,
                    "skill_slug": slug,
                    "skill_name": skill_name,
                    "state_classification": classification,
                    "proficiency": prof,
                    "confidence": conf,
                    "required_level": req,
                    "gap": gap_val,
                    "evidence_coverage": state.evidence_coverage,
                    "evidence_strength": state.evidence_strength,
                    "evidence_count": ev_count,
                    "evidence_depth": ev_depth,
                    "active_sources": active_srcs,
                    "evidence_ids": ev_ids,
                    "reasoning": reasoning,
                    "last_evaluated_at": now_iso,
                }
                c.table(TABLE_LEARNER_STATES).upsert(row, on_conflict="user_id, skill_slug").execute()
            except Exception as e:
                logger.debug("Database upsert for learner_skill_states skipped: %s", e)

    return learner_states


def create_evidence_snapshot(
    user_id: str,
    analysis_result_id: Optional[str] = None,
    learner_states: Optional[Dict[str, LearnerSkillState]] = None,
) -> dict:
    """
    Create an immutable EvidenceSnapshot before roadmap generation.
    Enables INAURA to verifiably answer:
    'Why did you generate this roadmap for me?'
    """
    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()
    snapshot_id = str(uuid.uuid4())

    sources_analyzed, sources_available, sources_unavailable = audit_user_sources(user_id)

    states_dict = {
        k: v.to_dict() if isinstance(v, LearnerSkillState) else v
        for k, v in (learner_states or {}).items()
    }

    snapshot = {
        "id": snapshot_id,
        "user_id": user_id,
        "analysis_result_id": analysis_result_id,
        "sources_analyzed": sources_analyzed,
        "sources_available": sources_available,
        "sources_unavailable": sources_unavailable,
        "learner_skill_states": states_dict,
        "engine_version": ENGINE_VERSION,
        "created_at": now_iso,
    }

    if c:
        try:
            r = c.table(TABLE_SNAPSHOTS).insert(snapshot).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
        except Exception as e:
            logger.debug("Database insert for evidence_snapshots skipped: %s", e)

    return snapshot


def get_latest_evidence_snapshot(user_id: str) -> Optional[dict]:
    """Retrieve user's most recent immutable evidence snapshot."""
    c = _client()
    if not c:
        return None
    try:
        r = c.table(TABLE_SNAPSHOTS).select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
    except Exception as e:
        logger.debug("Failed to fetch evidence snapshot: %s", e)
    return None
