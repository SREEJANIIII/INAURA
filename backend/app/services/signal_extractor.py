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
# Heuristic prototype values — not scientifically validated, clearly documented.
# SOURCE RELIABILITY (weight) is separate from SIGNAL STRENGTH (proficiency evidence).
# Project reliability 0.90 must NOT automatically mean signal 0.90.
# Calibration per Phase 4C fix:
#  - tech list only → 0.30
#  - desc mention → 0.50
#  - explicit implementation → 0.65
#  - strong concrete evidence → 0.75
SIGNAL_STRENGTH = {
    "project_tech_only": 0.30,  # skill only in technology list, little depth
    "project_desc_mention": 0.50,  # skill mentioned in description
    "project_explicit_impl": 0.65,  # explicitly described as implemented/used
    "project_strong_impl": 0.75,  # strong concrete implementation evidence
    # Legacy keys kept for backward compatibility but recalibrated
    "project_tech_explicit": 0.30,
    "project_title_mention": 0.50,
    "cert_name_mention": 0.50,  # recalibrated: cert mention alone is moderate, not 0.70
    "cert_org_mention": 0.40,
    "evidence_url_platform": 0.70,  # deprecated: URL presence alone — do not use for skill proficiency
    "file_name_mention": 0.40,  # file name alone is weak
    "resume_mention": 0.35,
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

    # 1. Evidence URL sources — FIXED Phase 4C: URL presence alone does NOT imply proficiency
    # Previously platform_map created a fixed 0.70 signal for github->git, leetcode/codeforces->dsa,
    # kaggle->machine_learning, linkedin->communication, causing unrelated skills to all show 70%.
    # Per audit: GitHub/LeetCode/Codeforces/Kaggle/LinkedIn URLs only establish that a source was provided,
    # not substantive skill proficiency. No proficiency signal is created for URL-only evidence where
    # external data has not been fetched. Proficiency must come from explicit evidence (project tech,
    # descriptions, cert names, file titles, etc.). Source reliability remains separate as weight.
    # SIGNAL_STRENGTH["evidence_url_platform"] is deprecated for proficiency and not used here.
    for ev in evidence:
        et = ev.get("evidence_type")
        # Intentionally NO signal for github/leetcode/codeforces/kaggle/linkedin URL presence alone
        # (previously used fixed 0.70 which violated evidence-driven requirement)
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

    # 2. Projects — calibrated heuristic (prototype, not validated)
    # Signal must reflect evidence depth, not just tech list match.
    # - tech list only → 0.30
    # - desc mention → 0.50
    # - explicit implementation → 0.65
    # - strong concrete → 0.75
    # Source reliability (project 0.90) is weight, separate from signal.
    def _assess_desc_depth(desc_text: str) -> str:
        """Return depth tag for overall description: tech_only, desc_mention, explicit, strong"""
        dl = (desc_text or "").lower()
        # Strong concrete indicators — multiple specific implementation details
        strong_concrete = ["jwt", "indexing", "caching", "automated test", "docker", "deployment", "kubernetes", "testing", "test"]
        strong_count = sum(1 for kw in strong_concrete if kw in dl)
        # Explicit implementation indicators
        explicit_keywords = ["implemented", "built", "designed", "developed", "created", "using", "with", "integrated", "deployed", "authentication", "crud", "database", "fastapi", "postgresql", "rest api", "api"]
        has_explicit = any(kw in dl for kw in explicit_keywords)
        if strong_count >= 3:
            return "strong"
        if has_explicit and strong_count >= 1:
            # B case: authentication+crud+database → explicit
            return "explicit"
        if has_explicit and len(dl.strip()) > 40:
            # Longer desc with verbs but few strong keywords → explicit
            # need at least one skill-relevant keyword to be explicit, checked per skill
            return "explicit"
        return "weak"

    for proj in projects:
        techs = proj.get("technologies") or []
        desc = (proj.get("description") or "") + " " + (proj.get("name") or "")
        desc_lower = desc.lower()
        # Collect tech canonicals
        tech_canonicals = set()
        for tech in techs:
            parts = [p.strip() for p in tech.replace("+", ",").split(",") if p.strip()]
            for part in parts:
                canonical = normalize_skill(part, client)
                if canonical:
                    tech_canonicals.add(canonical)
        # Collect desc canonicals by scanning words
        desc_canonicals = set()
        for word in desc.replace(",", " ").replace(".", " ").replace(":", " ").replace(";", " ").split():
            if len(word) < 3:
                continue
            # Also handle phrases like "REST" separately; normalize each word, but for "REST API" we need bigram
            # For now try single word; multi-word skills like rest_apis will be found via alias "api" or "rest"
            canonical = normalize_skill(word, client)
            if canonical:
                desc_canonicals.add(canonical)
        # Also check multi-word substrings for skills like "rest api", "rest apis"
        # Simple substring check for known multi-word skills
        for canon in ["rest_apis", "machine_learning", "data_visualization"]:
            # Use display name alias check via normalize_skill on phrase
            if canon.replace("_", " ") in desc_lower or canon in desc_lower:
                # Verify via normalize
                if normalize_skill(canon.replace("_", " "), client) or normalize_skill(canon, client):
                    # Only add if not already via word scan
                    normed = normalize_skill(canon.replace("_", " "), client)
                    if normed:
                        desc_canonicals.add(normed)
                    else:
                        desc_canonicals.add(canon)

        # Overall desc depth for tech-only escalation
        overall_depth = _assess_desc_depth(desc)

        # Handle tech-list skills with calibrated depth
        for canonical in tech_canonicals:
            is_in_desc = canonical in desc_canonicals
            # Also check substring for robustness (e.g., "Python" in desc)
            if not is_in_desc and canonical.lower() in desc_lower:
                is_in_desc = True
            # Determine signal key
            if is_in_desc:
                if overall_depth == "strong":
                    sig_key = "project_strong_impl"
                elif overall_depth in ("explicit",):
                    sig_key = "project_explicit_impl"
                else:
                    sig_key = "project_desc_mention"
            else:
                # Tech only, not in desc
                if overall_depth == "strong":
                    sig_key = "project_strong_impl"
                elif overall_depth == "explicit":
                    sig_key = "project_explicit_impl"
                else:
                    sig_key = "project_tech_only"
            sig_val = SIGNAL_STRENGTH[sig_key]
            # Explanation reflects depth
            if sig_key == "project_tech_only":
                expl = f"'{canonical}' listed in project '{proj.get('name')}' technologies (tech list only, little depth)"
            elif sig_key == "project_desc_mention":
                expl = f"Skill '{canonical}' mentioned in project '{proj.get('name')}' description"
            elif sig_key == "project_explicit_impl":
                expl = f"Skill '{canonical}' explicitly described as implemented/used in project '{proj.get('name')}'"
            else:
                expl = f"Skill '{canonical}' strong concrete implementation in project '{proj.get('name')}'"
            signals.append(
                _make_signal(
                    canonical,
                    "project",
                    sig_val,
                    expl,
                    project_id=proj.get("id"),
                )
            )
        # Handle desc-only skills (in desc but not in tech)
        for canonical in desc_canonicals:
            if canonical in tech_canonicals:
                continue
            # Desc-only: 0.50, 0.65, 0.75 based on depth
            if overall_depth == "strong":
                sig_key = "project_strong_impl"
            elif overall_depth == "explicit":
                sig_key = "project_explicit_impl"
            else:
                sig_key = "project_desc_mention"
            sig_val = SIGNAL_STRENGTH[sig_key]
            signals.append(
                _make_signal(
                    canonical,
                    "project",
                    sig_val,
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
