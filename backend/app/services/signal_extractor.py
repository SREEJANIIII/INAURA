from typing import List, Dict, Any
from ..core.supabase import get_supabase_client
from .skill_taxonomy import normalize_skill

# Configurable source reliability weights — heuristic prototype values
SOURCE_RELIABILITY = {
    "github": 0.90,           # project / github evidence
    "project": 0.90,
    "leetcode": 0.85,         # coding platform
    "codeforces": 0.85,
    "kaggle": 0.85,
    "syllabus": 0.80,         # coursework
    "coursework": 0.80,
    "certification": 0.65,
    "certification_file": 0.65,
    "resume": 0.50,
    "linkedin": 0.40,
    "self_declared": 0.30,
    "project_doc": 0.75,
}

# Signal strength per extraction context (before reliability)
SIGNAL_STRENGTH = {
    "project_tech_explicit": 0.90,  # skill in project technologies
    "project_desc_mention": 0.60,
    "project_title_mention": 0.55,
    "cert_name_mention": 0.70,
    "cert_org_mention": 0.50,
    "evidence_url_platform": 0.70,  # platform presence itself
    "file_name_mention": 0.50,
    "resume_mention": 0.45,
}


def _reliability(source_type: str) -> float:
    return SOURCE_RELIABILITY.get(source_type, 0.50)


def _make_signal(
    canonical: str,
    source_type: str,
    signal_value: float,
    explanation: str,
    evidence_id=None,
    project_id=None,
    certification_id=None,
    metadata=None,
) -> dict:
    return {
        "canonical_name": canonical,
        "source_type": source_type,
        "signal_value": max(0, min(1, signal_value)),
        "source_reliability": _reliability(source_type),
        "explanation": explanation,
        "evidence_id": evidence_id,
        "project_id": project_id,
        "certification_id": certification_id,
        "metadata": metadata or {},
    }


def extract_signals(
    evidence: List[dict],
    projects: List[dict],
    certifications: List[dict],
) -> List[dict]:
    """
    Deterministic extraction from stored evidence.
    Returns list of signals with canonical skill, source_type, signal_value, reliability, explanation.
    """
    client = get_supabase_client()
    if client is None:
        return []

    signals: List[dict] = []

    # Helper to try normalize and add signal
    def try_add(raw_skill: str, source_type: str, strength_key: str, explanation: str, **ids):
        canonical = normalize_skill(raw_skill, client)
        if not canonical:
            return
        sig_val = SIGNAL_STRENGTH.get(strength_key, 0.5)
        signals.append(_make_signal(canonical, source_type, sig_val, explanation, **ids))

    # 1. Evidence URL sources — platform signals
    platform_map = {
        "github": ("git", "GitHub profile present"),
        "leetcode": ("dsa", "LeetCode profile present — indicates DSA practice"),
        "codeforces": ("dsa", "Codeforces profile present — indicates DSA practice"),
        "kaggle": ("machine_learning", "Kaggle profile present — indicates ML/data experience"),
        "linkedin": ("communication", "LinkedIn profile present"),
    }
    for ev in evidence:
        et = ev.get("evidence_type")
        if et in platform_map:
            canonical, expl = platform_map[et]
            # Verify canonical exists
            if normalize_skill(canonical, client):
                signals.append(
                    _make_signal(
                        canonical,
                        et,
                        SIGNAL_STRENGTH["evidence_url_platform"],
                        f"{expl} (source: {ev.get('source_url')})",
                        evidence_id=ev.get("id"),
                    )
                )
        # Also check title/source_url for skill mentions? Keep conservative for now
        # For resume/syllabus file evidence, we could extract from title
        if et in ("resume", "syllabus", "certification_file", "project_doc"):
            title = ev.get("title") or ev.get("file_path") or ""
            # Try to extract skills from title (e.g., "ML_Resume.pdf" contains ML)
            for word in title.replace("_", " ").replace("-", " ").split():
                canonical = normalize_skill(word, client)
                if canonical:
                    signals.append(
                        _make_signal(
                            canonical,
                            et,
                            SIGNAL_STRENGTH["file_name_mention"],
                            f"Skill '{canonical}' inferred from file name '{title}'",
                            evidence_id=ev.get("id"),
                        )
                    )

    # 2. Projects — technologies explicit, description/title mentions
    for proj in projects:
        techs = proj.get("technologies") or []
        desc = (proj.get("description") or "") + " " + (proj.get("name") or "")
        for tech in techs:
            # Split tech string which may be comma separated already, but we have list
            # Each tech may be "Python" or "React + TypeScript"
            parts = [p.strip() for p in tech.replace("+", ",").split(",") if p.strip()]
            for part in parts:
                canonical = normalize_skill(part, client)
                if canonical:
                    signals.append(
                        _make_signal(
                            canonical,
                            "project",
                            SIGNAL_STRENGTH["project_tech_explicit"],
                            f"'{canonical}' explicitly listed in project '{proj.get('name')}' technologies",
                            project_id=proj.get("id"),
                        )
                    )
        # Description mentions — moderate signal
        for word in desc.replace(",", " ").replace(".", " ").split():
            # Only try longer words to avoid noise
            if len(word) < 3:
                continue
            canonical = normalize_skill(word, client)
            if canonical:
                # Avoid duplicate if already added via tech explicit for same project+skill
                already = any(s["canonical_name"] == canonical and s.get("project_id") == proj.get("id") and s["source_type"] == "project" for s in signals)
                if not already:
                    signals.append(
                        _make_signal(
                            canonical,
                            "project",
                            SIGNAL_STRENGTH["project_desc_mention"],
                            f"Skill '{canonical}' mentioned in project '{proj.get('name')}' description",
                            project_id=proj.get("id"),
                        )
                    )

    # 3. Certifications — name and issuing org
    for cert in certifications:
        name = cert.get("name") or ""
        org = cert.get("issuing_org") or ""
        # Check name for skills
        for word in name.replace("-", " ").replace("/", " ").split():
            if len(word) < 3:
                continue
            canonical = normalize_skill(word, client)
            if canonical:
                signals.append(
                    _make_signal(
                        canonical,
                        "certification",
                        SIGNAL_STRENGTH["cert_name_mention"],
                        f"Skill '{canonical}' inferred from certification '{name}'",
                        certification_id=cert.get("id"),
                    )
                )
        # Org may contain skill? less likely, but check
        for word in org.split():
            canonical = normalize_skill(word, client)
            if canonical and len(word) > 4:
                signals.append(
                    _make_signal(
                        canonical,
                        "certification",
                        SIGNAL_STRENGTH["cert_org_mention"],
                        f"Skill '{canonical}' inferred from issuing org '{org}'",
                        certification_id=cert.get("id"),
                    )
                )

    # Deduplicate signals that are identical (same skill, same source id)
    # Keep all for evidence diversity, but limit to one per canonical+source+evidence
    # For now return all
    return signals
