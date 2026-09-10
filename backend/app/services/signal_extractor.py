import re
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timezone

from ..core.supabase import get_supabase_client
from .skill_taxonomy import normalize_skill, normalize_skill_slug, extract_known_skills_from_text
from .evidence.base import EvidenceDepth, VerificationStatus
from .evidence.github import GitHubProvider, parse_github_url
from .evidence.manager import evidence_manager, get_evidence_dedup_key

# Configurable source reliability weights — heuristic prototype values
# Hierarchy: performance-based (leetcode/codeforces/kaggle 0.85) and verified
# coursework (0.80) > GitHub supporting evidence (0.70, MEDIUM) >
# certifications (0.55, MEDIUM-LOW) > resume/linkedin/self-declared (LOW).
SOURCE_RELIABILITY: Dict[str, float] = {
    "github": 0.70,           # supporting repo evidence, not a definitive test
    "project": 0.90,          # concrete project work
    "leetcode": 0.85,         # verified coding assessment platform
    "codeforces": 0.85,
    "kaggle": 0.85,
    "syllabus": 0.80,         # accredited coursework
    "coursework": 0.80,
    "project_doc": 0.75,      # technical project documentation
    "certification": 0.55,    # industry certification (MEDIUM-LOW)
    "certification_file": 0.55,
    "resume": 0.50,           # self-reported resume document
    "linkedin": 0.40,         # social profile
    "self_declared": 0.30,    # unverified declaration
}

# Calibrated signal strengths by depth
SIGNAL_STRENGTH: Dict[str, float] = {
    "project_tech_only": 0.30,
    "project_desc_mention": 0.50,
    "project_explicit_impl": 0.65,
    "project_strong_impl": 0.75,
    # Legacy keys kept for backward compatibility
    "project_tech_explicit": 0.30,
    "project_title_mention": 0.50,
    "cert_name_mention": 0.50,
    "cert_org_mention": 0.40,
    "evidence_url_platform": 0.0,  # URL presence alone yields 0 proficiency
    "file_name_mention": 0.40,
    "resume_mention": 0.35,
    "resume_action": 0.50,
}


def _reliability(source_type: str) -> float:
    return SOURCE_RELIABILITY.get(source_type, 0.50)


def _make_signal(
    canonical: str,
    source_type: str,
    signal_value: float,
    explanation: str,
    evidence_id: Optional[str] = None,
    project_id: Optional[str] = None,
    certification_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Construct a structured Skill Signal conforming to:
    1. Core conceptual model: skill, source, signal_strength, source_reliability, evidence_id, reason
    2. Backward-compatible fields: canonical_name, source_type, signal_value, explanation
    """
    bounded_val = max(0.0, min(1.0, float(signal_value)))
    reliability_val = _reliability(source_type)
    return {
        # Core conceptual signal model
        "skill": canonical,
        "source": source_type,
        "signal_strength": bounded_val,
        "source_reliability": reliability_val,
        "evidence_id": evidence_id,
        "reason": explanation,
        # Backward compatibility with DB schema and tests
        "canonical_name": canonical,
        "source_type": source_type,
        "signal_value": bounded_val,
        "explanation": explanation,
        "project_id": project_id,
        "certification_id": certification_id,
        "metadata": metadata or {},
    }


def _assess_desc_depth(desc_text: str) -> str:
    """Assess implementation depth of project description."""
    dl = (desc_text or "").lower()
    strong_concrete = [
        "jwt", "indexing", "caching", "automated test", "automated tests",
        "docker", "deployment", "kubernetes", "testing", "test",
        "microservices", "redis", "ci/cd", "pipeline"
    ]
    strong_count = sum(1 for kw in strong_concrete if kw in dl)

    explicit_keywords = [
        "implemented", "built", "designed", "developed", "created",
        "using", "with", "integrated", "deployed", "authentication",
        "crud", "database", "fastapi", "postgresql", "rest api", "api"
    ]
    has_explicit = any(kw in dl for kw in explicit_keywords)

    if strong_count >= 3:
        return "strong"
    if has_explicit and strong_count >= 1:
        return "explicit"
    if has_explicit and len(dl.strip()) > 40:
        return "explicit"
    return "weak"


def extract_signals(
    evidence: List[dict],
    projects: List[dict],
    certifications: List[dict],
) -> List[dict]:
    """
    Deterministic skill signal extraction across all evidence forms.
    - Unverified URL-only claims yield 0 proficiency signals.
    - Verified external evidence (e.g. GitHub inspected repositories) yields concrete technical signals.
    - Handles deduplication to prevent double-counting the exact same repository or project.
    """
    client = get_supabase_client()
    signals: List[dict] = []
    seen_evidence_keys: Set[str] = set()
    inspected_github_repos: Set[str] = set()

    # 1. Inspect Evidence Items (URLs + Files)
    github_provider = GitHubProvider()

    for ev in evidence:
        et = (ev.get("evidence_type") or "").lower()
        src_url = ev.get("source_url") or ""

        # Deduplication check across all platform profiles and repositories
        dedup_key = get_evidence_dedup_key(ev)
        if dedup_key in seen_evidence_keys:
            continue
        seen_evidence_keys.add(dedup_key)

        provider = evidence_manager.get_provider(ev)
        if provider:
            src_type = provider.provider_name

            # Check for mock inspection fixture (for offline testing)
            if "mock_inspection" in ev:
                if src_type == "github":
                    owner, repo, _ = parse_github_url(src_url)
                    if owner and repo:
                        inspected_github_repos.add(f"{owner.lower()}/{repo.lower()}")
                    res = provider._build_result_from_inspection(
                        owner=owner or "mock",
                        repo=repo or "mock-repo",
                        inspection=ev["mock_inspection"],
                        verified_at=datetime.now(timezone.utc),
                    )
                else:
                    res = provider._build_result_from_inspection(
                        ev["mock_inspection"],
                        verified_at=datetime.now(timezone.utc),
                    )

                for sig in res.signals:
                    signals.append(
                        _make_signal(
                            canonical=sig.skill,
                            source_type=src_type,
                            signal_value=sig.signal_strength,
                            explanation=sig.reason,
                            evidence_id=ev.get("id"),
                            metadata=sig.metadata,
                        )
                    )
                continue

            # Check if verified previously and stored in metadata
            meta = ev.get("metadata") or {}
            v_status = ev.get("verification_status") or meta.get("verification_status")
            verified_signals = meta.get("verified_signals")

            if src_type == "github" and src_url:
                owner, repo, _ = parse_github_url(src_url)
                if owner and repo:
                    inspected_github_repos.add(f"{owner.lower()}/{repo.lower()}")

            if v_status in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED) and isinstance(verified_signals, list):
                for sig in verified_signals:
                    signals.append(
                        _make_signal(
                            canonical=sig.get("skill", sig.get("canonical_name", "")),
                            source_type=src_type,
                            signal_value=sig.get("signal_strength", sig.get("signal_value", 0.5)),
                            explanation=sig.get("reason", sig.get("explanation", "")),
                            evidence_id=ev.get("id"),
                            metadata=sig.get("metadata"),
                        )
                    )
                continue

            # If unverified URL only, do NOT produce proficiency signal (depth Level 0 = 0.00)
            continue

        # B. File Evidence (resume, syllabus, certification_file, project_doc)
        if et in ("resume", "syllabus", "certification_file", "project_doc"):
            meta = ev.get("metadata") or {}
            parsed_text = meta.get("parsed_text") or meta.get("text") or meta.get("content") or ev.get("content") or ""
            sections = meta.get("sections") or {}
            explicit_skills = meta.get("skills") or []

            # Combine full document text from sections or parsed_text
            full_doc_text = str(parsed_text)
            if isinstance(sections, dict):
                full_doc_text += " " + " ".join(str(v) for v in sections.values())

            # If explicit structured skills provided in metadata
            if isinstance(explicit_skills, list) and explicit_skills:
                for raw_s in explicit_skills:
                    c = normalize_skill(str(raw_s), client)
                    if c:
                        signals.append(
                            _make_signal(
                                canonical=c,
                                source_type=et,
                                signal_value=SIGNAL_STRENGTH.get("resume_mention", 0.35),
                                explanation=f"Skill '{c}' self-reported in {et} skills section",
                                evidence_id=ev.get("id"),
                                metadata={"self_reported": True, "section": "skills"},
                            )
                        )

            if full_doc_text.strip():
                # Aspirational & Beginner phrase patterns:
                # Skills mentioned exclusively in aspirational/seeking contexts must NOT be credited as confirmed abilities
                aspirational_patterns = [
                    re.compile(r'\b(?:interested in|looking to|eager to|hoping to|seeking to|want to|plan to)\s+learn\b', re.I),
                    re.compile(r'\b(?:interested in|exploring|future interest(?:\s+in)?)\b', re.I),
                    re.compile(r'\b(?:beginner in|basic knowledge of|familiarity with|introductory knowledge of)\b', re.I),
                ]
                concrete_action_verbs = [
                    "implemented", "built", "engineered", "developed", "architected",
                    "deployed", "designed", "created", "scaled", "automated", "optimized",
                    "migrated", "configured", "maintained", "refactored"
                ]

                # Segment text into sentences/bullet points
                raw_sentences = re.split(r'[\r\n•\-\*]+|[.;]+(?:\s+|$)', full_doc_text)
                extracted_doc_skills: Dict[str, dict] = {}

                for sentence in raw_sentences:
                    sent = sentence.strip()
                    if not sent or len(sent) < 3:
                        continue
                    sent_lower = sent.lower()

                    # Check if sentence is aspirational
                    is_aspirational = any(p.search(sent) for p in aspirational_patterns)

                    # Extract skills present in this sentence
                    sent_skills: Set[str] = set()
                    for word in sent.replace(",", " ").replace("/", " ").split():
                        if len(word) >= 2:
                            c = normalize_skill(word, client)
                            if c:
                                sent_skills.add(c)
                    for sk in extract_known_skills_from_text(sent, client):
                        sent_skills.add(sk.display_name)

                    for skill_name in sent_skills:
                        if is_aspirational:
                            if skill_name not in extracted_doc_skills:
                                extracted_doc_skills[skill_name] = {"confirmed": False, "is_action": False, "sent": sent}
                        else:
                            has_action = any(v in sent_lower for v in concrete_action_verbs)
                            if skill_name not in extracted_doc_skills or not extracted_doc_skills[skill_name]["confirmed"]:
                                extracted_doc_skills[skill_name] = {"confirmed": True, "is_action": has_action, "sent": sent}
                            elif has_action:
                                extracted_doc_skills[skill_name]["is_action"] = True

                # Generate signals for confirmed non-aspirational skills
                for skill_name, info in extracted_doc_skills.items():
                    if not info["confirmed"]:
                        # Excluded because it only appeared in an aspirational context
                        continue
                    is_action = info["is_action"]
                    val = SIGNAL_STRENGTH.get("resume_action", 0.50) if is_action else SIGNAL_STRENGTH.get("resume_mention", 0.35)
                    expl = (
                        f"Skill '{skill_name}' described with concrete implementation in {et}"
                        if is_action else
                        f"Skill '{skill_name}' self-reported claim in {et}"
                    )
                    signals.append(
                        _make_signal(
                            canonical=skill_name,
                            source_type=et,
                            signal_value=val,
                            explanation=expl,
                            evidence_id=ev.get("id"),
                            metadata={"self_reported": True, "has_action_verbs": is_action},
                        )
                    )
            elif not explicit_skills:
                # Fallback to filename tokenization only if no document content available
                title = ev.get("title") or ev.get("file_path") or ""
                for word in title.replace("_", " ").replace("-", " ").replace(".", " ").split():
                    if len(word) < 2:
                        continue
                    canonical = normalize_skill(word, client)
                    if canonical:
                        signals.append(
                            _make_signal(
                                canonical=canonical,
                                source_type=et,
                                signal_value=SIGNAL_STRENGTH["file_name_mention"],
                                explanation=f"Skill '{canonical}' inferred from file name '{title}' (unparsed document)",
                                evidence_id=ev.get("id"),
                            )
                        )

    # 2. Projects Evidence (with cross-source deduplication)
    seen_project_keys: Set[str] = set()
    for proj in projects:
        name = (proj.get("name") or "").strip()
        proj_key = name.lower()
        if proj_key in seen_project_keys:
            continue
        seen_project_keys.add(proj_key)

        # Cross-source deduplication with inspected GitHub repositories
        gh_url = proj.get("github_url") or ""
        is_linked_to_inspected_repo = False
        if gh_url:
            p_owner, p_repo, _ = parse_github_url(gh_url)
            if p_owner and p_repo:
                repo_slug = f"{p_owner.lower()}/{p_repo.lower()}"
                if repo_slug in inspected_github_repos:
                    # Prevent double-counting: repository codebase was already inspected by GitHub provider
                    is_linked_to_inspected_repo = True

        if is_linked_to_inspected_repo:
            # Code was already verified from repository files and commits.
            # Do not emit duplicate skill signals that double-count the same codebase.
            continue

        techs = proj.get("technologies") or []
        raw_desc = proj.get("description") or ""
        student_contrib = proj.get("student_contribution") or ""
        desc_full = f"{raw_desc} {student_contrib} {name}"
        desc_lower = desc_full.lower()

        # Collect skills from technology list
        tech_canonicals: Set[str] = set()
        for tech in techs:
            parts = [p.strip() for p in tech.replace("+", ",").split(",") if p.strip()]
            for part in parts:
                canonical = normalize_skill(part, client)
                if canonical:
                    tech_canonicals.add(canonical)

        # Collect skills from description text using taxonomy scanning
        desc_canonicals: Set[str] = set()
        for word in desc_full.replace(",", " ").replace(".", " ").replace(":", " ").replace(";", " ").split():
            if len(word) < 3:
                continue
            canonical = normalize_skill(word, client)
            if canonical:
                desc_canonicals.add(canonical)

        for phrase_skill in extract_known_skills_from_text(desc_full, client):
            desc_canonicals.add(phrase_skill.display_name)
            desc_canonicals.add(phrase_skill.id)

        overall_depth = _assess_desc_depth(desc_full)

        # Skills in technologies list
        for canonical in tech_canonicals:
            is_in_desc = canonical in desc_canonicals or canonical.lower() in desc_lower
            if is_in_desc:
                if overall_depth == "strong":
                    sig_key = "project_strong_impl"
                    expl = f"Skill '{canonical}' strong concrete implementation in project '{name}'"
                elif overall_depth == "explicit":
                    sig_key = "project_explicit_impl"
                    expl = f"Skill '{canonical}' explicitly described as implemented/used in project '{name}'"
                else:
                    sig_key = "project_desc_mention"
                    expl = f"Skill '{canonical}' mentioned in project '{name}' description"
            else:
                if overall_depth == "strong":
                    sig_key = "project_strong_impl"
                    expl = f"Skill '{canonical}' strong concrete implementation in project '{name}'"
                elif overall_depth == "explicit":
                    sig_key = "project_explicit_impl"
                    expl = f"Skill '{canonical}' explicitly described as implemented/used in project '{name}'"
                else:
                    sig_key = "project_tech_only"
                    expl = f"'{canonical}' listed in project '{name}' technologies (tech list only, little depth)"

            meta_payload = {"project_name": name}
            if student_contrib:
                meta_payload["student_contribution"] = student_contrib

            signals.append(
                _make_signal(
                    canonical=canonical,
                    source_type="project",
                    signal_value=SIGNAL_STRENGTH[sig_key],
                    explanation=expl,
                    project_id=proj.get("id"),
                    metadata=meta_payload,
                )
            )

        # Skills mentioned only in description (not in tech list)
        for canonical in desc_canonicals:
            if canonical in tech_canonicals:
                continue
            if overall_depth == "strong":
                sig_key = "project_strong_impl"
            elif overall_depth == "explicit":
                sig_key = "project_explicit_impl"
            else:
                sig_key = "project_desc_mention"

            meta_payload = {"project_name": name}
            if student_contrib:
                meta_payload["student_contribution"] = student_contrib

            signals.append(
                _make_signal(
                    canonical=canonical,
                    source_type="project",
                    signal_value=SIGNAL_STRENGTH[sig_key],
                    explanation=f"Skill '{canonical}' mentioned in project '{name}' description",
                    project_id=proj.get("id"),
                    metadata=meta_payload,
                )
            )

    # 3. Certifications Evidence
    known_cert_vendors: Dict[str, str] = {
        "amazon web services": "AWS",
        "aws": "AWS",
        "google cloud": "Google Cloud",
        "gcp": "Google Cloud",
        "microsoft": "Azure",
        "azure": "Azure",
        "hashicorp": "Terraform",
        "linux foundation": "Linux",
        "red hat": "Linux",
        "oracle": "Java",
        "cisco": "Computer Networking",
    }

    current_year = datetime.now(timezone.utc).year

    for cert in certifications:
        name = cert.get("name") or ""
        org = (cert.get("issuing_org") or "").strip()
        org_lower = org.lower()
        comp_year = cert.get("completion_year")
        is_outdated = False
        if comp_year and isinstance(comp_year, int):
            if comp_year < current_year - 5:
                is_outdated = True

        cert_skills: Set[str] = set()

        # Skill from certification name
        for word in name.replace("-", " ").replace("/", " ").split():
            if len(word) < 3:
                continue
            canonical = normalize_skill(word, client)
            if canonical:
                cert_skills.add(canonical)

        for phrase_skill in extract_known_skills_from_text(name, client):
            cert_skills.add(phrase_skill.display_name)

        # Map known vendor organization directly rather than naive word tokenization
        for vendor_key, vendor_canonical in known_cert_vendors.items():
            if vendor_key in org_lower:
                canonical = normalize_skill(vendor_canonical, client) or vendor_canonical
                cert_skills.add(canonical)

        # Emit certification signals
        base_val = SIGNAL_STRENGTH["cert_name_mention"]  # 0.50
        signal_val = round(base_val * 0.70, 2) if is_outdated else base_val

        for canonical in sorted(cert_skills):
            expl = f"Skill '{canonical}' inferred from certification '{name}' ({org})"
            if is_outdated:
                expl += f" (outdated, completed {comp_year})"
            signals.append(
                _make_signal(
                    canonical=canonical,
                    source_type="certification",
                    signal_value=signal_val,
                    explanation=expl,
                    certification_id=cert.get("id"),
                    metadata={"completion_year": comp_year, "is_outdated": is_outdated, "issuing_org": org},
                )
            )

    return signals
