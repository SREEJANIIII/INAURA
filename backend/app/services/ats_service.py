from __future__ import annotations

import io
import re
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from ..core.config import get_settings
from ..core.supabase import get_supabase_client
from . import document_parser
from . import industry_service
from .industry_roles import canonicalize_role_name, ROLE_CATALOG, list_catalog_roles
from .skill_taxonomy import extract_known_skills_from_text, normalize_skill, normalize_skill_slug
from ..schemas.ats import (
    AtsSkillMatch,
    AtsSectionDetail,
    AtsContactCheck,
    AtsScores,
    AtsRecommendation,
    AtsBulletRewrite,
    AtsTestResponse,
    AtsRoleOption,
)

logger = logging.getLogger(__name__)

# Curated high-impact action verbs used in ATS evaluation
ACTION_VERBS = [
    "accelerated", "achieved", "administered", "analyzed", "architected",
    "automated", "built", "collaborated", "compiled", "composed", "configured",
    "constructed", "coordinated", "created", "debugged", "decreased",
    "delivered", "deployed", "designed", "developed", "devised", "documented",
    "engineered", "enhanced", "established", "executed", "expanded",
    "expedited", "formulated", "generated", "implemented", "improved",
    "increased", "initiated", "inspected", "installed", "integrated",
    "investigated", "launched", "led", "leveraged", "maintained", "managed",
    "maximized", "mentored", "migrated", "minimized", "modeled",
    "modernized", "monitored", "optimized", "orchestrated", "overhauled",
    "pioneered", "planned", "produced", "programmed", "published",
    "redesigned", "reduced", "refactored", "resolved", "restructured",
    "revamped", "scaled", "simplified", "spearheaded", "standardized",
    "streamlined", "structured", "supervised", "tested", "tracked",
    "trained", "transformed", "upgraded", "validated"
]


def get_supported_ats_roles() -> List[AtsRoleOption]:
    """Return all catalog roles with their top benchmark skills."""
    roles = list_catalog_roles()
    options: List[AtsRoleOption] = []
    for r in roles:
        title = r["title"]
        reqs = industry_service.list_by_role(title)
        top_skills = [
            req.get("skill") for req in reqs if req.get("skill")
        ][:8]
        options.append(
            AtsRoleOption(
                title=title,
                slug=r["slug"],
                category=r["category"],
                description=r["description"],
                benchmark_skills=top_skills,
            )
        )
    return options


def _extract_contact_info(text: str, document_links: Optional[List[str]] = None) -> AtsContactCheck:
    """Detect presence of contact information and profiles in resume text and document hyperlinks."""
    doc_links = list(document_links or [])
    REJECTED_HANDLES = {
        "linkedin", "github", "www", "com", "profile", "in", "user",
        "http", "https", "link", "url", "portfolio", "email", "phone",
        "repo", "repositories", "org", "net", "io",
    }

    # 1. Email detection (from mailto: links, labeled email lines, and general regex)
    email = None
    for link in doc_links:
        if link.lower().startswith("mailto:"):
            email = link[7:].split("?")[0].strip().rstrip(".,);")
            break
    if not email:
        # Check labeled email e.g. "Email: user@example.com", "E-mail: user@example.com"
        labeled_email_match = re.search(
            r"(?:email|e-mail|mail)[:\s#\-\.]*([A-Za-z0-9._%+-]+(?:\s*@\s*|\s*\[at\]\s*)[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b",
            text,
            re.IGNORECASE,
        )
        if labeled_email_match:
            raw_email = labeled_email_match.group(1).strip().rstrip(".,);/")
            email = re.sub(r"\s*@\s*", "@", raw_email)
    if not email:
        # Standard email regex
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        emails = re.findall(email_pattern, text)
        if emails:
            email = emails[0].rstrip(".,);")
    if not email:
        # Regex allowing spaces around @ (common when fonts / layouts separate glyphs)
        spaced_email = re.search(r"\b[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b", text)
        if spaced_email:
            email = re.sub(r"\s*@\s*", "@", spaced_email.group(0).strip()).rstrip(".,);")

    # 2. Phone detection (from tel: links, labeled phone lines, and formatted patterns)
    phone = None
    for link in doc_links:
        if link.lower().startswith("tel:"):
            clean_tel = link[4:].split("?")[0].strip()
            digits = re.sub(r"\D", "", clean_tel)
            if 10 <= len(digits) <= 15:
                phone = clean_tel
                break
    if not phone:
        # Check labeled phone lines first (e.g. "Phone: +91 9876543210", "Mobile: 98765-43210", "Tel: (555) 019-2834")
        labeled_phone_pat = r"(?:phone|mobile|cell|contact(?:\s*no\.?)?|tel|telephone|call|ph|mob)[:\s#\-\.]*(\+?[0-9\(\)\s\.\-]{9,22}[0-9])\b"
        m = re.search(labeled_phone_pat, text, re.IGNORECASE)
        if m:
            cand = m.group(1).strip().rstrip(".,);")
            digits = re.sub(r"\D", "", cand)
            if 10 <= len(digits) <= 15:
                phone = cand

    if not phone:
        phone_patterns = [
            # Standard international with optional country code and spaces/hyphens e.g. +1 (555) 019-2834, +91 98765 43210, +44 20 7946 0958
            r"(?:\+\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}\b",
            # 10-12 digit Indian mobile / landline numbers e.g. +919876543210, 9876543210, +91 98765 43210
            r"\b(?:\+91[-.\s]?)?[6-9]\d{4}[-.\s]?\d{5}\b",
            r"\b(?:\+91[-.\s]?)?[6-9]\d{9}\b",
            # 5-5 digit grouping e.g. 98765 43210 or 98765-43210
            r"\b[6-9]\d{4}[-.\s]\d{5}\b",
            # Standard domestic 10 digits
            r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
            # Domestic with leading 0 e.g. 09876543210
            r"\b0[6-9]\d{9}\b",
        ]
        for pat in phone_patterns:
            m = re.search(pat, text)
            if m:
                cand = m.group(0).strip().rstrip(".,);")
                digits = re.sub(r"\D", "", cand)
                if 10 <= len(digits) <= 15:
                    phone = cand
                    break

    # 3. LinkedIn profile detection
    linkedin = None
    for link in doc_links:
        if "linkedin.com" in link.lower():
            linkedin = link.strip().rstrip(".,);")
            break
    if not linkedin:
        li_matches = re.findall(r"(?:https?://)?(?:www\.)?linkedin\.com/(?:in|pub|company)/[a-zA-Z0-9_\-\.%]+", text, re.IGNORECASE)
        if li_matches:
            cand = li_matches[0].strip().rstrip(".,);/")
            linkedin = cand if cand.startswith("http") else f"https://{cand}"
        else:
            li_user_match = re.search(r"\blinkedin(?:\.com)?[\s:/|\-]+(?:in/)?([a-zA-Z0-9_\-\.]{3,35})\b", text, re.IGNORECASE)
            if li_user_match:
                username = li_user_match.group(1).strip()
                if username.lower() not in REJECTED_HANDLES and not username.lower().endswith(".com"):
                    linkedin = f"https://linkedin.com/in/{username}"

    # 4. GitHub / portfolio detection
    github = None
    for link in doc_links:
        llow = link.lower()
        if "github.com" in llow or ".github.io" in llow:
            github = link.strip().rstrip(".,);")
            break
    if not github:
        gh_matches = re.findall(r"(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9_\-\.%]+", text, re.IGNORECASE)
        if gh_matches:
            cand = gh_matches[0].strip().rstrip(".,);/")
            github = cand if cand.startswith("http") else f"https://{cand}"
        else:
            gh_io = re.findall(r"(?:https?://)?([a-zA-Z0-9_\-\.]+)\.github\.io\b", text, re.IGNORECASE)
            if gh_io:
                cand = gh_io[0].strip()
                github = f"https://{cand}.github.io"
            else:
                gh_user_match = re.search(r"\bgithub[\s:/|\-]+@?([a-zA-Z0-9_\-\.]{3,35})\b", text, re.IGNORECASE)
                if gh_user_match:
                    username = gh_user_match.group(1).strip()
                    if username.lower() not in REJECTED_HANDLES and not username.lower().endswith(".com"):
                        github = f"https://github.com/{username}"

    # 5. Personal Portfolio / Website detection
    portfolio = None
    for link in doc_links:
        llow = link.lower()
        if not ("linkedin.com" in llow or "github.com" in llow or llow.startswith("mailto:") or llow.startswith("tel:")):
            portfolio = link.strip().rstrip(".,);")
            break
    if not portfolio:
        port_matches = re.findall(r"(?:https?://)?(?:www\.)?[a-zA-Z0-9_\-\.]+\.(?:dev|me|tech|io|app|site|vercel\.app|netlify\.app)(?:/[^\s<>]*)?", text, re.IGNORECASE)
        for pm in port_matches:
            if not ("github.com" in pm.lower() or "linkedin.com" in pm.lower()):
                cand = pm.strip().rstrip(".,);/")
                portfolio = cand if cand.startswith("http") else f"https://{cand}"
                break

    # Combine distinct links
    combined_links = []
    seen_urls = set()

    def _add_link(u: Optional[str]):
        if not u:
            return
        norm = u.lower().rstrip("/")
        if norm not in seen_urls and not norm.startswith("mailto:") and not norm.startswith("tel:"):
            seen_urls.add(norm)
            combined_links.append(u)

    _add_link(linkedin)
    _add_link(github)
    _add_link(portfolio)
    for dl in doc_links:
        _add_link(dl)

    return AtsContactCheck(
        has_email=bool(email),
        email=email,
        has_phone=bool(phone),
        phone=phone,
        has_linkedin=bool(linkedin),
        linkedin_url=linkedin,
        has_github=bool(github),
        github_url=github,
        has_portfolio=bool(portfolio),
        portfolio_url=portfolio,
        all_links=list(dict.fromkeys(combined_links)),
    )


def _detect_sections(text: str, parsed_sections: Dict[str, str]) -> List[AtsSectionDetail]:
    """Inspect standard ATS sections in document."""
    low_text = text.lower()

    # Check parsed_sections and contextual cues
    has_contact = (
        "contact" in parsed_sections
        or bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b", text))
        or "contact" in low_text[:600]
    )

    has_summary = (
        "summary" in parsed_sections
        or bool(re.search(r"\b(professional\s+summary|career\s+objective|summary|about\s+me|personal\s+profile)\b", low_text))
    )

    has_experience = (
        "experience" in parsed_sections
        or bool(re.search(r"\b(work\s+experience|professional\s+experience|employment\s+history|experience|internships?|work\s+history)\b", low_text))
    )

    has_education = (
        "education" in parsed_sections
        or bool(re.search(r"\b(education|academic\s+background|academics|university|b\.tech|bachelor|master|degree)\b", low_text))
    )

    has_skills = (
        "skills" in parsed_sections
        or bool(re.search(r"\b(technical\s+skills|core\s+competencies|skills|tech\s+stack|technologies|proficiencies)\b", low_text))
    )

    has_projects = (
        "projects" in parsed_sections
        or bool(re.search(r"\b(projects|technical\s+projects|personal\s+projects|academic\s+projects|open\s+source)\b", low_text))
    )

    has_certifications = (
        "certifications" in parsed_sections
        or bool(re.search(r"\b(certifications?|certificates?|licenses?|credentials|accreditations)\b", low_text))
    )

    return [
        AtsSectionDetail(
            name="Contact Information",
            found=has_contact,
            importance="critical",
            description="Email, phone number, and location in document header.",
        ),
        AtsSectionDetail(
            name="Technical / Core Skills",
            found=has_skills,
            importance="critical",
            description="Dedicated technical skills section with programming languages and tools.",
        ),
        AtsSectionDetail(
            name="Experience / Work History",
            found=has_experience,
            importance="critical",
            description="Chronological work, internship, or employment history with bullet points.",
        ),
        AtsSectionDetail(
            name="Education",
            found=has_education,
            importance="critical",
            description="Degree, major, university, and graduation timeframe.",
        ),
        AtsSectionDetail(
            name="Projects",
            found=has_projects,
            importance="important",
            description="Concrete software or data projects showing practical implementation.",
        ),
        AtsSectionDetail(
            name="Professional Summary",
            found=has_summary,
            importance="optional",
            description="Brief 2-3 line overview highlighting your target role and key strengths.",
        ),
        AtsSectionDetail(
            name="Certifications & Achievements",
            found=has_certifications,
            importance="optional",
            description="Recognized industry certifications, hackathons, or academic honors.",
        ),
    ]


def _find_action_verbs(text: str) -> List[str]:
    """Find unique action verbs used in resume text."""
    low = " " + re.sub(r"[^\w\s]", " ", text.lower()) + " "
    found = set()
    for verb in ACTION_VERBS:
        if re.search(r"\b" + re.escape(verb) + r"\b", low):
            found.add(verb)
    return sorted(list(found))


def _find_quantifiable_metrics(text: str) -> List[str]:
    """Find quantified metric expressions in resume."""
    patterns = [
        r"\b\d+(?:\.\d+)?%",  # percentages e.g. 40%, 99.9%
        r"\b\d+(?:\.\d+)?\s*(?:x|k|m|million|billion)\b",  # scale e.g. 10k, 3x, 2 million
        r"\b\d+\s*(?:ms|seconds|sec|minutes)\b",  # latency e.g. 200ms, 5 seconds
        r"(?:\$|€|£|₹|rs\.?\s*)\d+(?:,\d{3})*(?:\.\d+)?",  # monetary
        r"\b\d+\s*(?:users|clients|customers|requests|req/s|queries|qps|endpoints|models)\b",  # volume
        r"(?:reduced|increased|improved|saved|optimized|scaled)\s+by\s+\d+",  # delta phrases
    ]
    matches = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            s = m.group(0).strip()
            if len(s) >= 2:
                matches.add(s)
    return sorted(list(matches))[:15]


def _extract_requirements_for_role(
    role_name: str,
    job_description: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve canonical role requirements, augmenting with JD skills if provided."""
    canon = canonicalize_role_name(role_name)
    requirements: List[Dict[str, Any]] = []

    if canon:
        raw_reqs = industry_service.list_by_role(canon)
        for r in raw_reqs:
            requirements.append({
                "skill": r.get("skill"),
                "category": r.get("skill_category", "General"),
                "importance": float(r.get("importance", 0.75)),
                "role_relevance": r.get("role_relevance", "CORE"),
            })
    else:
        # Custom role fallback
        requirements = [
            {"skill": "Data Structures & Algorithms", "category": "Computer Science", "importance": 0.85, "role_relevance": "CORE"},
            {"skill": "Git", "category": "Tools", "importance": 0.85, "role_relevance": "CORE"},
            {"skill": "REST APIs", "category": "Development", "importance": 0.80, "role_relevance": "CORE"},
            {"skill": "SQL", "category": "Databases", "importance": 0.80, "role_relevance": "CORE"},
            {"skill": "Testing", "category": "Quality", "importance": 0.75, "role_relevance": "IMPORTANT"},
            {"skill": "Docker", "category": "DevOps", "importance": 0.70, "role_relevance": "IMPORTANT"},
            {"skill": "System Design", "category": "Architecture", "importance": 0.80, "role_relevance": "CORE"},
        ]

    # Augment with skills explicitly mentioned in job description
    if job_description and job_description.strip():
        jd_skills = extract_known_skills_from_text(job_description)
        existing_skills = {r["skill"].lower() for r in requirements if r.get("skill")}
        for js in jd_skills:
            if js.display_name.lower() not in existing_skills:
                requirements.append({
                    "skill": js.display_name,
                    "category": js.category,
                    "importance": 0.85,
                    "role_relevance": "JOB SPECIFIC",
                })
                existing_skills.add(js.display_name.lower())

    return requirements


def _match_skills(
    text: str,
    requirements: List[Dict[str, Any]],
) -> Tuple[List[AtsSkillMatch], List[AtsSkillMatch], List[str]]:
    """Match resume text against role requirements and extract extra tech skills."""
    low_text = " " + re.sub(r"[^\w\s\+\#\./\-]", " ", text.lower()) + " "

    # All known skills in resume
    known_skills = extract_known_skills_from_text(text)
    known_by_display = {s.display_name.lower(): s for s in known_skills}
    known_by_id = {s.id.lower(): s for s in known_skills}

    matched: List[AtsSkillMatch] = []
    missing: List[AtsSkillMatch] = []
    matched_names = set()

    for req in requirements:
        skill_name = req["skill"]
        category = req.get("category", "General")
        importance = req.get("importance", 0.7)
        role_rel = req.get("role_relevance", "IMPORTANT")

        # Direct search or canonical match
        clean_name = skill_name.lower()
        slug = normalize_skill_slug(skill_name)

        is_present = False
        occurrences = 0

        if clean_name in known_by_display or (slug and slug in known_by_id):
            is_present = True

        # Regex count check for occurrences
        escaped = re.escape(clean_name)
        matches = re.findall(r"(?:\b|_)" + escaped + r"(?:\b|_)", low_text)
        occurrences = len(matches)
        if occurrences > 0:
            is_present = True
        elif is_present:
            occurrences = 1

        match_item = AtsSkillMatch(
            skill=skill_name,
            category=category,
            importance=importance,
            matched=is_present,
            occurrences=occurrences,
            role_relevance=role_rel,
        )

        if is_present:
            matched.append(match_item)
            matched_names.add(clean_name)
            if slug:
                matched_names.add(slug)
        else:
            missing.append(match_item)

    # Sort matched by occurrences descending, missing by importance descending
    matched.sort(key=lambda x: (x.occurrences, x.importance), reverse=True)
    missing.sort(key=lambda x: x.importance, reverse=True)

    # Extra skills detected that were not in target requirements
    extra: List[str] = []
    for s in known_skills:
        if s.display_name.lower() not in matched_names and s.id.lower() not in matched_names:
            extra.append(s.display_name)

    return matched, missing, sorted(list(set(extra)))[:15]


def _calculate_ats_scores(
    matched_skills: List[AtsSkillMatch],
    missing_skills: List[AtsSkillMatch],
    sections: List[AtsSectionDetail],
    contact: AtsContactCheck,
    action_verbs: List[str],
    metrics: List[str],
    word_count: int,
    parse_status: str,
) -> AtsScores:
    """Calculate granular scores for ATS dimensions and weighted overall score."""
    # 1. Skills & Keywords Match (0-100)
    total_importance = sum(m.importance for m in matched_skills) + sum(m.importance for m in missing_skills)
    matched_importance = sum(m.importance for m in matched_skills)
    if total_importance > 0:
        base_skills_score = (matched_importance / total_importance) * 100.0
    else:
        base_skills_score = 70.0
    
    # Reward repeated mentions of core skills
    depth_bonus = min(8.0, len([m for m in matched_skills if m.occurrences >= 2]) * 1.5)
    skills_match_score = int(min(100.0, max(10.0, base_skills_score + depth_bonus)))

    # 2. Impact & Action Verbs (0-100)
    verb_count = len(action_verbs)
    if verb_count >= 8:
        verb_score = 45.0
    elif verb_count >= 5:
        verb_score = 35.0
    elif verb_count >= 3:
        verb_score = 25.0
    elif verb_count >= 1:
        verb_score = 15.0
    else:
        verb_score = 5.0

    metric_count = len(metrics)
    if metric_count >= 5:
        metric_score = 45.0
    elif metric_count >= 3:
        metric_score = 35.0
    elif metric_count >= 1:
        metric_score = 20.0
    else:
        metric_score = 5.0

    diversity_bonus = 10.0 if (verb_count >= 4 and metric_count >= 2) else 0.0
    impact_score = int(min(100.0, verb_score + metric_score + diversity_bonus))

    # 3. Section Completeness (0-100)
    sec_map = {s.name: s.found for s in sections}
    sections_score_val = 0.0
    if sec_map.get("Contact Information"):
        sections_score_val += 20.0
    if sec_map.get("Technical / Core Skills"):
        sections_score_val += 25.0
    if sec_map.get("Experience / Work History"):
        sections_score_val += 25.0
    if sec_map.get("Education"):
        sections_score_val += 15.0
    if sec_map.get("Projects"):
        sections_score_val += 15.0
    # Bonus for summary or certs
    if sec_map.get("Professional Summary") or sec_map.get("Certifications & Achievements"):
        sections_score_val = min(100.0, sections_score_val + 5.0)
    sections_structure_score = int(min(100.0, sections_score_val))

    # 4. Formatting, Parseability & Contact Integrity (0-100)
    format_val = 0.0
    # Word count score
    if 400 <= word_count <= 950:
        format_val += 40.0
    elif 300 <= word_count < 400 or 950 < word_count <= 1300:
        format_val += 30.0
    elif 200 <= word_count < 300 or 1300 < word_count <= 1700:
        format_val += 20.0
    else:
        format_val += 10.0

    # Contact channels score
    if contact.has_email:
        format_val += 15.0
    if contact.has_phone:
        format_val += 15.0
    if contact.has_linkedin or contact.has_github or contact.has_portfolio:
        format_val += 15.0
    if (contact.has_linkedin and contact.has_github) or contact.has_portfolio:
        format_val += 15.0

    # Parse health
    if parse_status == "ok":
        format_val = min(100.0, format_val)
    else:
        format_val = max(10.0, format_val - 20.0)
    formatting_score = int(min(100.0, format_val))

    # Overall weighted score
    # 40% skills + 25% impact + 20% sections + 15% formatting
    overall = int(round(
        0.40 * skills_match_score
        + 0.25 * impact_score
        + 0.20 * sections_structure_score
        + 0.15 * formatting_score
    ))
    overall = min(100, max(0, overall))

    return AtsScores(
        overall=overall,
        skills_match=skills_match_score,
        impact_metrics=impact_score,
        sections_structure=sections_structure_score,
        formatting_parseability=formatting_score,
    )


def _generate_recommendations(
    scores: AtsScores,
    missing_skills: List[AtsSkillMatch],
    sections: List[AtsSectionDetail],
    contact: AtsContactCheck,
    word_count: int,
    action_verbs: List[str],
    metrics: List[str],
    target_role: str,
) -> List[AtsRecommendation]:
    """Generate prioritized, actionable recommendations to improve ATS score."""
    recs: List[AtsRecommendation] = []

    # Missing critical skills
    critical_missing = [m.skill for m in missing_skills if m.importance >= 0.85]
    if critical_missing:
        sample = ", ".join(critical_missing[:4])
        recs.append(
            AtsRecommendation(
                title=f"Incorporate Critical Role Skills: {sample}",
                description=f"Your target role ({target_role}) strongly prioritizes {sample}. ATS scanners filter resumes that lack these core keywords. Add them into your Skills section and demonstrate their practical application in your project bullet points.",
                category="skills",
                priority="high",
            )
        )

    # Quantifiable metrics
    if len(metrics) < 3:
        recs.append(
            AtsRecommendation(
                title="Quantify Accomplishments with Concrete Metrics",
                description="Your resume has few numerical results. Use Google's XYZ formula: 'Accomplished [X], as measured by [Y], by doing [Z]'. Example: 'Reduced API response latency by 35% through Redis caching and query indexing'.",
                category="impact",
                priority="high",
            )
        )

    # Action verbs
    if len(action_verbs) < 5:
        recs.append(
            AtsRecommendation(
                title="Start Bullet Points with High-Impact Action Verbs",
                description="Replace passive phrasing like 'Responsible for' or 'Helped with' with active engineering verbs such as 'Architected', 'Engineered', 'Orchestrated', 'Optimized', or 'Deployed'.",
                category="impact",
                priority="medium",
            )
        )

    # Missing critical sections
    missing_sec_names = [s.name for s in sections if not s.found and s.importance == "critical"]
    if missing_sec_names:
        recs.append(
            AtsRecommendation(
                title=f"Add Missing Standard Sections: {', '.join(missing_sec_names)}",
                description="ATS parsers rely on standard headings to categorize your background. Ensure your resume has explicit section headers for Contact Information, Technical Skills, Experience, and Education.",
                category="sections",
                priority="high",
            )
        )

    # Contact details
    if not contact.has_email or not contact.has_phone:
        recs.append(
            AtsRecommendation(
                title="Include Explicit Contact Details in the Header",
                description="Ensure both an active professional email and phone number are clearly stated at the top of your resume in clean text (avoid putting them inside embedded images or complex header graphics).",
                category="format",
                priority="high",
            )
        )

    if not contact.has_linkedin or not contact.has_github:
        recs.append(
            AtsRecommendation(
                title="Add Clean Links to LinkedIn & GitHub",
                description="Technical recruiters and modern ATS platforms verify your technical footprint. Add direct, clean URLs to your LinkedIn profile and GitHub repository showcase.",
                category="format",
                priority="medium",
            )
        )

    # Word count / Length
    if word_count < 350:
        recs.append(
            AtsRecommendation(
                title="Expand Resume Depth (Currently Under 350 Words)",
                description=f"At {word_count} words, your resume appears brief to ATS keyword density analyzers. Expand your technical project descriptions, technologies used, and engineering responsibilities.",
                category="format",
                priority="medium",
            )
        )
    elif word_count > 1100:
        recs.append(
            AtsRecommendation(
                title="Condense Content for Maximum Scannability",
                description=f"Your resume contains {word_count} words. For early to mid-career engineers, keep the document focused on the most relevant 1-2 pages (around 500-800 words).",
                category="format",
                priority="low",
            )
        )

    # Secondary missing skills
    important_missing = [m.skill for m in missing_skills if 0.70 <= m.importance < 0.85]
    if important_missing and len(recs) < 5:
        sample_imp = ", ".join(important_missing[:3])
        recs.append(
            AtsRecommendation(
                title=f"Add Supporting Domain Skills: {sample_imp}",
                description=f"To stand out above the average applicant threshold for {target_role}, mention familiarity with supporting tools such as {sample_imp}.",
                category="skills",
                priority="low",
            )
        )

    return recs[:5]


def _generate_bullet_rewrites(target_role: str, matched: List[AtsSkillMatch], missing: List[AtsSkillMatch]) -> List[AtsBulletRewrite]:
    """Generate contextual bullet rewrites illustrating the XYZ achievement framework."""
    # Context-aware templates based on role
    role_lower = target_role.lower()

    if "frontend" in role_lower:
        return [
            AtsBulletRewrite(
                original="Worked on the React website UI and made it faster.",
                improved="Engineered 14 responsive React components using TypeScript and Tailwind CSS, reducing initial page load time by 42% and boosting mobile accessibility score to 98/100.",
                explanation="Specifies exact stack (TypeScript, Tailwind), quantity of components, and measurable performance improvement (42% faster load).",
            ),
            AtsBulletRewrite(
                original="Implemented API integration for user data.",
                improved="Integrated RESTful endpoints with React Query for client-side caching and optimistic UI updates, decreasing redundant server calls by 60%.",
                explanation="Replaces passive phrasing with technical details on caching strategies and network savings.",
            ),
        ]
    elif "data" in role_lower or "analyst" in role_lower or "science" in role_lower:
        return [
            AtsBulletRewrite(
                original="Analyzed company customer data using SQL and Python.",
                improved="Queried 2.4M customer transaction records using PostgreSQL window functions and Pandas, identifying churn trends that informed a 15% retention campaign boost.",
                explanation="Mentions dataset scale (2.4M records), specific analytical tools (window functions, Pandas), and commercial business impact.",
            ),
            AtsBulletRewrite(
                original="Created dashboards for executive team.",
                improved="Designed and deployed automated PowerBI dashboards tracking 12 core KPI metrics, reducing monthly cross-functional reporting overhead by 18 hours.",
                explanation="Focuses on automation, specific metric count, and hours saved.",
            ),
        ]
    else:  # Backend / Software Engineer / General
        return [
            AtsBulletRewrite(
                original="Created backend REST APIs for the application.",
                improved="Architected and deployed 12 RESTful microservice endpoints using Python and FastAPI, handling 15,000+ daily requests with sub-120ms p95 latency.",
                explanation="Adds scale (15k daily requests), latency benchmark (sub-120ms), and production architecture details.",
            ),
            AtsBulletRewrite(
                original="Setup Docker and database for the project.",
                improved="Containerized multi-tier backend services using Docker and orchestrated PostgreSQL database migrations, reducing local developer onboarding time from 3 hours to 15 minutes.",
                explanation="Demonstrates developer productivity impact and container orchestration mastery.",
            ),
        ]


async def _enrich_with_ai_insights(
    text: str,
    target_role: str,
    scores: AtsScores,
    recs: List[AtsRecommendation],
    rewrites: List[AtsBulletRewrite],
) -> Tuple[str, List[AtsBulletRewrite]]:
    """Optionally enhance findings with Gemini LLM if API key is configured."""
    settings = get_settings()
    if not settings.google_api_key:
        # Fallback to high-fidelity deterministic summary
        summary = (
            f"Resume evaluated for '{target_role}'. Score is {scores.overall}/100 ({scores.skills_match}% keyword match). "
            f"Strengths identified in technical skills and parseability. Focus on addressing missing role competencies "
            f"and quantifying project outcomes with concrete numerical results."
        )
        return summary, rewrites

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model or "gemini-2.5-flash",
            google_api_key=settings.google_api_key,
            temperature=0.3,
            timeout=12,
        )

        prompt = f"""You are an elite Technical Recruiter and ATS Optimization Specialist.
Evaluate this resume text against the target role: "{target_role}".
ATS Overall Score: {scores.overall}/100.
Keywords Match: {scores.skills_match}%.
Impact/Metrics: {scores.impact_metrics}%.

Resume Excerpt (first 2500 chars):
\"\"\"{text[:2500]}\"\"\"

Task:
1. Provide a concise 2-sentence executive summary from an ATS recruiter lens.
2. Select 2 weak or generic lines from the resume text and rewrite them in Google XYZ format ("Accomplished [X] as measured by [Y], by doing [Z]").

Respond with STRICT JSON ONLY:
{{
  "summary": "2-sentence recruiter summary",
  "bullet_rewrites": [
    {{"original": "original phrase from resume", "improved": "optimized impactful version", "explanation": "why this passes ATS"}},
    {{"original": "second phrase", "improved": "optimized version", "explanation": "rationale"}}
  ]
}}
"""
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Extract json
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(content[start:end+1])
            ai_summary = data.get("summary") or ""
            ai_rewrites = data.get("bullet_rewrites") or []
            coerced_rewrites = []
            for r in ai_rewrites:
                if isinstance(r, dict) and r.get("original") and r.get("improved"):
                    coerced_rewrites.append(
                        AtsBulletRewrite(
                            original=str(r["original"]),
                            improved=str(r["improved"]),
                            explanation=str(r.get("explanation", "Optimized with concrete metrics and action verbs.")),
                        )
                    )
            if ai_summary and coerced_rewrites:
                return ai_summary, coerced_rewrites
    except Exception as e:
        logger.info(f"Gemini ATS enrichment bypassed: {e}")

    # Fallback deterministic summary
    summary = (
        f"Resume evaluated for '{target_role}'. Score: {scores.overall}/100 ({scores.skills_match}% keywords match). "
        f"Key focus: incorporate critical role competencies and quantify project outcomes with numbers and percentages."
    )
    return summary, rewrites


async def test_resume_ats(
    file_bytes: bytes,
    filename: str,
    target_role: str,
    job_description: Optional[str] = None,
    content_type: Optional[str] = None,
) -> AtsTestResponse:
    """Complete ATS scan and job-role match analysis."""
    # 1. Parse document text and sections
    parsed = document_parser.parse_document_bytes(
        file_bytes,
        filename=filename,
        content_type=content_type,
    )

    raw_text = parsed.get("parsed_text", "")
    if not raw_text or not raw_text.strip():
        status = parsed.get("parse_status", "failed")
        warning = parsed.get("parse_warning", "Could not extract text from document.")
        raise HTTPException(
            status_code=400,
            detail=f"Unable to read resume text ({warning}). Please upload a text-based PDF or Word document (.docx).",
        )

    sections_dict = parsed.get("sections", {})
    word_count = parsed.get("word_count", len(raw_text.split()))
    char_count = parsed.get("text_char_count", len(raw_text))
    # 2. Extract contact information and profile links
    document_links = parsed.get("links", [])
    contact = _extract_contact_info(raw_text, document_links)

    # 3. Detect document sections
    sections = _detect_sections(raw_text, sections_dict)

    # 4. Action verbs & metrics
    action_verbs = _find_action_verbs(raw_text)
    metrics = _find_quantifiable_metrics(raw_text)

    # 5. Role requirements & skills matching
    requirements = _extract_requirements_for_role(target_role, job_description)
    matched_skills, missing_skills, extra_skills = _match_skills(raw_text, requirements)

    # 6. Granular scoring
    scores = _calculate_ats_scores(
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        sections=sections,
        contact=contact,
        action_verbs=action_verbs,
        metrics=metrics,
        word_count=word_count,
        parse_status=parsed.get("parse_status", "ok"),
    )

    # 7. Grade and verdict
    if scores.overall >= 88:
        grade = "A+"
        verdict = "Excellent · High ATS Pass Probability"
    elif scores.overall >= 78:
        grade = "A"
        verdict = "Strong · High ATS Pass Probability"
    elif scores.overall >= 68:
        grade = "B"
        verdict = "Competitive · Moderate ATS Pass Probability"
    elif scores.overall >= 52:
        grade = "C"
        verdict = "Needs Work · Below Average ATS Match"
    else:
        grade = "D"
        verdict = "Low Match · High ATS Filter Rejection Risk"

    # 8. Improvement recommendations
    recommendations = _generate_recommendations(
        scores=scores,
        missing_skills=missing_skills,
        sections=sections,
        contact=contact,
        word_count=word_count,
        action_verbs=action_verbs,
        metrics=metrics,
        target_role=target_role,
    )

    # 9. Bullet rewrites & summary
    base_rewrites = _generate_bullet_rewrites(target_role, matched_skills, missing_skills)
    summary, final_rewrites = await _enrich_with_ai_insights(
        text=raw_text,
        target_role=target_role,
        scores=scores,
        recs=recommendations,
        rewrites=base_rewrites,
    )

    # Form response
    return AtsTestResponse(
        filename=filename,
        target_role=target_role,
        word_count=word_count,
        char_count=char_count,
        scores=scores,
        grade=grade,
        verdict=verdict,
        summary=summary,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        extra_skills=extra_skills,
        sections=sections,
        contact=contact,
        action_verbs_found=action_verbs,
        metrics_found=metrics,
        recommendations=recommendations,
        bullet_rewrites=final_rewrites,
        parsed_text_preview=raw_text[:2500] + ("\n...[Preview truncated]" if len(raw_text) > 2500 else ""),
        parse_status=parsed.get("parse_status", "ok"),
        parse_warning=parsed.get("parse_warning"),
    )
