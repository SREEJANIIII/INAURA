"""Evidence-backed resume assembly, verification, and LaTeX export."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from . import evidence_service, industry_service, profile_service
from .industry_roles import canonicalize_role_name
from .skill_taxonomy import extract_known_skills_from_text, get_canonical_skill, normalize_skill

TABLE = "resumes"
_METRIC_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:%|percent|users?|ms|seconds?|x)\b", re.I)


def _client():
    c = get_supabase_client()
    if c is None:
        raise HTTPException(503, "Supabase is not configured")
    return c


def _row(row: dict) -> dict:
    return {**row, "content": row.get("content") or {}, "claims": row.get("claims") or []}


def list_resumes(user_id: str) -> List[dict]:
    return [_row(x) for x in (_client().table(TABLE).select("*").eq("user_id", user_id).order("updated_at", desc=True).execute().data or [])]


def get_resume(user_id: str, resume_id: str) -> dict:
    r = _client().table(TABLE).select("*").eq("user_id", user_id).eq("id", resume_id).maybe_single().execute()
    if not r.data:
        raise HTTPException(404, "Resume not found")
    return _row(r.data)


def _requirements(role: str) -> List[dict]:
    canonical = canonicalize_role_name(role)
    if not canonical:
        raise HTTPException(400, "Choose a role from INAURA's role catalog")
    return industry_service.list_by_role(canonical)


def _name(row: dict) -> str:
    return str(row.get("name") or row.get("title") or "").strip()


def _clean(text: Any) -> str:
    """Collapse whitespace; never invent content, only tidy it."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _nonempty(text: Any) -> str:
    return _clean(text)


def _sentence(text: Any) -> str:
    """Tidy a user/evidence sentence and ensure terminal punctuation."""
    t = _clean(text).rstrip(".")
    return f"{t}." if t else ""


def _project_score(project: dict, required: set[str]) -> tuple[int, list[str]]:
    techs = [str(x).strip() for x in (project.get("technologies") or []) if str(x).strip()]
    matched = [normalize_skill(x) or x for x in techs if (normalize_skill(x) or x) in required or normalize_skill(x) in required]
    # Canonical display names for matched technologies, order-stable.
    matched = list(dict.fromkeys(matched))
    score = len(matched) * 3 + (2 if project.get("github_url") else 0) + (1 if project.get("project_url") else 0)
    # Real substance signals only: documented contribution and description depth.
    if _clean(project.get("student_contribution")):
        score += 2
    if len(_clean(project.get("description"))) >= 100:
        score += 1
    score += min(len(techs), 5)
    return score, matched


def _load_skill_assessments(user_id: str) -> List[dict]:
    """Read the existing canonical skill assessments; never use roadmap rows."""
    try:
        result = _client().table("skill_assessments").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
        rows = result.data or []
        skills = _client().table("skills").select("id,canonical_name,display_name,category").execute().data or []
        by_id = {str(row.get("id")): row for row in skills}
        output = []
        seen = set()
        for row in rows:
            skill = by_id.get(str(row.get("skill_id")), {})
            name = skill.get("display_name") or skill.get("canonical_name")
            if not name or name.lower() in seen:
                continue
            evidence_count = int(row.get("evidence_count") or 0)
            proficiency = float(row.get("proficiency") or 0)
            if evidence_count <= 0 and proficiency <= 0:
                continue
            output.append({"name": name, "category": skill.get("category") or "Skills", "proficiency": proficiency,
                           "confidence": float(row.get("confidence") or 0), "evidence_count": evidence_count,
                           "source": "skill_assessment", "id": row.get("skill_id")})
            seen.add(name.lower())
        return output
    except Exception:
        # Older installations may not have assessment tables yet; projects/evidence remain usable.
        return []


def _doc_sections(evidence: List[dict]) -> tuple[dict, Optional[str]]:
    """Parsed sections from the user's uploaded resume/syllabus (existing parser output).

    Returns (sections, evidence_id). Empty when no parsed document exists.
    """
    for ev in evidence or []:
        if ev.get("is_excluded"):
            continue
        if str(ev.get("evidence_type") or "").lower() not in ("resume", "syllabus"):
            continue
        sections = ((ev.get("metadata") or {}).get("sections") or {})
        if isinstance(sections, dict) and any(str(v or "").strip() for v in sections.values()):
            return sections, ev.get("id")
    return {}, None


def _sanitize_doc_text(text: Any) -> str:
    """Clean PDF/parser-derived text without altering legitimate content.

    - Drops U+FFFD replacement characters (parser corruption, never real text).
    - Normalizes dash variants to "-" / "—" consistent with latex_escape,
      which renders "—" as "---".
    - Collapses repeated whitespace (newlines preserved for segmentation).
    """
    t = str(text or "")
    t = t.replace("�", "")
    t = t.replace("­", "")  # soft hyphen: artifact of line wrapping
    t = t.replace("–", "-").replace("−", "-").replace("‐", "-")
    t = t.replace("—", " — ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" +\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _split_entries(text: Any) -> List[str]:
    text = _sanitize_doc_text(text)
    parts = re.split(r"[●•\n]+", text)
    out = []
    for part in parts:
        cleaned = _clean(part).strip(" -–—")
        if len(cleaned) >= 8:
            out.append(cleaned)
    return out


_TITLE_LEAD_VERBS = frozenset({
    "built", "implemented", "designed", "developed", "created", "resolved",
    "added", "fixed", "deployed", "pivoted", "integrated", "used", "using",
    "contributed", "led", "managed", "authored", "wrote", "tested", "debugged",
    "optimized", "refactored", "migrated", "launched", "shipped", "maintained",
    "building", "developing", "creating", "implementing", "designing",
    "resolved", "resolving", "initially",
})


def _starts_with_verb(line: str) -> bool:
    first = re.split(r"\s+", str(line or "").strip(), maxsplit=1)[0].lower().strip("(-–—\"'“”")
    return first in _TITLE_LEAD_VERBS


def _has_heading_separator(line: str) -> bool:
    return bool(re.search(r"\s[—–|]\s|\s-\s", str(line or "")))


def _looks_like_title(line: str) -> bool:
    """Conservative heading test: length alone is never sufficient.

    A title must additionally avoid sentence punctuation, implementation-verb
    leads, and (for marker-less lines) needs positional/structural support
    which the caller (_parse_doc_projects) provides. Kept as a shared guard
    so no caller relies on length by itself.
    """
    t = str(line or "").strip()
    if not t or len(t) > 90 or t.endswith((".", "!", "?", ":", ";")):
        return False
    if _starts_with_verb(t):
        return False
    return True


_WRAP_CONJUNCTIONS = frozenset({"and", "or", "but", "nor", "for", "so", "yet"})


def _continues_previous(text: str) -> bool:
    """Whether a line is a wrapped continuation of the previous line.

    Cues: trailing comma, trailing conjunction, or a trailing hyphen from
    PDF line-wrap hyphenation. Deterministic and documented.
    """
    t = str(text or "").rstrip()
    if not t:
        return False
    if t.endswith((",", "-")):
        return True
    last = re.split(r"\s+", t)[-1].lower().strip("(-–—\"'“”.,;:!?")
    return last in _WRAP_CONJUNCTIONS


def _parse_doc_projects(text: Any) -> List[dict]:
    """Group a parsed projects section into {title, bullets} preserving provenance.

    Bullet provenance is structural, never guessed:
      - A line introduced by a ●/• marker is ALWAYS bullet content.
      - A marker-less line that continues the previous line (trailing comma,
        conjunction, wrap hyphen) is joined to it, never promoted to a title.
      - A marker-less line becomes a title only when it passes the heading
        guard AND either carries an explicit heading separator (em dash /
        pipe / spaced hyphen) or directly precedes bullet content.
    Titles/bullets come verbatim from the document; nothing is discarded —
    unmatched text is preserved as bullets on the current project.
    """
    text = _sanitize_doc_text(text)
    seq: List[tuple[str, str]] = []  # (origin, line); origin in {"free", "bullet"}
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "●" in line or "•" in line:
            pre, _, post = line.partition("●" if "●" in line else "•")
            pre, post = pre.strip(), post.strip()
            if pre:
                seq.append(("free", pre))
            if post:
                seq.append(("bullet", post))
        else:
            seq.append(("free", line))

    # Join wrapped continuation lines into the previous entry.
    joined: List[tuple[str, str]] = []
    for origin, line in seq:
        if joined and _continues_previous(joined[-1][1]):
            prev_origin, prev_line = joined[-1]
            if prev_line.endswith("-") and not prev_line.endswith(" -"):
                merged = prev_line[:-1] + line  # de-hyphenate wrap: "rec-" + "ommender"
            else:
                merged = f"{prev_line} {line}"
            joined[-1] = (prev_origin, merged)
        else:
            joined.append((origin, line))

    # Classify free lines; bullet-origin lines are never title candidates.
    # A trailing free line inside a bullet segment may still be a heading when
    # it carries an explicit separator ("MirrorVibes — Live Project").
    entries: List[tuple[str, str]] = []
    for i, (origin, line) in enumerate(joined):
        if origin == "bullet":
            entries.append(("bullet", line))
            continue
        # Free line: check whether the NEXT kept line starts bullet content.
        followed_by_bullet = any(o == "bullet" for o, _ in joined[i + 1:i + 3])
        if _looks_like_title(line) and (_has_heading_separator(line) or followed_by_bullet):
            entries.append(("title", line))
        else:
            entries.append(("bullet", line))

    # Promote separator-headed trailing lines inside bullet runs to titles.
    final: List[tuple[str, str]] = []
    for kind, line in entries:
        if kind == "bullet" and _has_heading_separator(line) and _looks_like_title(line):
            # A heading separator inside bullet content marks the next project
            # (e.g. "...never loses\\nMirrorVibes — Live Project" arrived here
            # only when wrapping rules did not join them, i.e. no continuation
            # cue was present).
            final.append(("title", line))
        else:
            final.append((kind, line))

    projects: List[dict] = []
    for kind, entry in final:
        if kind == "title":
            projects.append({"title": entry, "bullets": []})
            continue
        bullet = _sentence(entry)
        if len(bullet) < 10:
            continue
        if not projects:
            projects.append({"title": "", "bullets": []})
        projects[-1]["bullets"].append(bullet)
    return [p for p in projects if p["title"] or p["bullets"]]


_ACHIEVEMENT_HINTS = ("hackathon", "ranked", "leaderboard", "award", "winner", "won ", "top ",
                      "participat", "qualif", "finalist", "scholar")


def _is_subsection_heading(entry: str) -> bool:
    """Detect subsection headings (e.g. "OPEN SOURCE") leaked from resume sections.

    All-caps short lines without lowercase letters are headings, not content.
    Deterministic: length-bounded, requires >= 3 alpha characters.
    """
    t = str(entry or "").strip().rstrip(".")
    if not t or len(t) > 40:
        return False
    letters = [c for c in t if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _split_experience_achievements(text: Any) -> tuple[List[str], List[str]]:
    """Split a parsed experience/activity section into experience vs achievements.

    Hackathon placements, ranks, and participations read as achievements;
    ongoing roles and memberships stay as experience. Keyword rule is
    deterministic and documented; source text is preserved verbatim.
    """
    experience, achievements = [], []
    for entry in _split_entries(text):
        if _is_subsection_heading(entry):
            continue
        low = entry.lower()
        target = achievements if any(h in low for h in _ACHIEVEMENT_HINTS) else experience
        target.append(_sentence(entry))
    return experience, achievements


def _canonical_names(values: Iterable[Any]) -> List[str]:
    """Map raw technology tokens to canonical display names where possible.

    Unmapped tokens are dropped here (kept separately as raw resume techs).
    """
    out = []
    for value in values or []:
        name = normalize_skill(str(value or ""))
        if name and name not in out:
            out.append(name)
    return out


def _github_repo_techs(repo: dict) -> List[str]:
    """Demonstrated repository technologies: languages by bytes + topics.

    Canonical names where the taxonomy knows them, raw keys otherwise.
    """
    langs = repo.get("languages") or {}
    ordered = sorted(langs.items(), key=lambda kv: -(kv[1] or 0)) if isinstance(langs, dict) else []
    techs = [(normalize_skill(str(name)) or str(name)) for name, _ in ordered[:5]]
    for topic in (repo.get("topics") or [])[:6]:
        name = normalize_skill(str(topic)) or str(topic).strip()
        if name and name not in techs:
            techs.append(name)
    primary = repo.get("language")
    if primary:
        name = normalize_skill(str(primary)) or str(primary)
        if name not in techs:
            techs.insert(0, name)
    return [t for t in techs if t][:6]


def _repo_rank(repo: dict, required: set[str]) -> tuple[int, List[str]]:
    techs = _github_repo_techs(repo)
    matched = [t for t in techs if t in required]
    try:
        stars = int(repo.get("stars") or repo.get("watchers") or 0)
    except (TypeError, ValueError):
        stars = 0
    score = len(matched) * 4 + (2 if _clean(repo.get("description")) else 0) + min(max(stars, 0), 3)
    return score, matched


def _norm_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


_REPO_ACRONYMS = frozenset({
    "ai", "api", "ui", "ux", "db", "os", "ml", "dl", "nlp", "cv", "iot",
    "ar", "vr", "3d", "2d", "css", "html", "js", "ts", "sql", "aws", "gcp",
    "ci", "cd", "oauth", "jwt", "orm", "sdk", "cli", "ide", "dns", "http",
    "json", "rest", "crud", "saas",
})
_REPO_MINOR_WORDS = frozenset({
    "with", "and", "or", "for", "of", "the", "a", "an", "in", "on", "to", "vs",
})


def humanize_repo_name(name: Any) -> str:
    """Render a repository slug as a readable display title.

    Rules: "-" / "_" become spaces; safe CamelCase boundaries are split;
    known acronyms keep uppercase; other words take title case except minor
    words mid-title. The repository URL/identifier is never altered (the
    caller keeps it separately); only the display string is produced here.
    """
    slug = re.sub(r"[-_]+", " ", str(name or "")).strip()
    slug = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", slug)
    slug = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", slug)
    words = [w for w in re.split(r"\s+", slug) if w]
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if low in _REPO_ACRONYMS:
            out.append(word.upper())
        elif low in _REPO_MINOR_WORDS and i > 0:
            out.append(low)
        elif word.isupper() or word.islower():
            out.append(word.capitalize() if len(word) > 1 else word.upper())
        else:
            out.append(word)  # preserve existing mixed case (McDonald, iTunes)
    return " ".join(out)


_GENERIC_NAME_TOKENS = frozenset({
    "project", "projects", "app", "apps", "live", "application", "applications",
    "game", "console", "based", "using", "with", "full", "stack", "my", "the",
    "a", "an", "and", "or", "of", "for", "to", "in", "on",
})


def _name_tokens(name: Any) -> set[str]:
    """Distinctive tokens of a project name: lowercase, punctuation removed,
    hyphen/underscore/CamelCase split, generic terms dropped."""
    raw = re.sub(r"[-_]+", " ", str(name or ""))
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    raw = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", raw)
    return {t.lower() for t in re.split(r"[^A-Za-z0-9]+", raw)
            if t and t.lower() not in _GENERIC_NAME_TOKENS and len(t) > 1}


def _likely_same_project(name_a: Any, name_b: Any) -> bool:
    """Deterministic near-duplicate check via distinctive-token overlap.

    Same project when the names share >= 2 distinctive tokens (a single
    shared token such as "AI" never merges unrelated projects). No fuzzy
    string similarity is used.
    """
    tokens_a, tokens_b = _name_tokens(name_a), _name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) >= 2


def _github_repos(evidence: List[dict]) -> tuple[List[dict], str, Optional[str], Optional[str]]:
    """Owned GitHub repositories with inspection data (existing verification output)."""
    for ev in evidence or []:
        if str(ev.get("evidence_type") or "").lower() != "github" or ev.get("is_excluded"):
            continue
        inspection = ((ev.get("metadata") or {}).get("inspection") or {})
        owner = str(inspection.get("owner") or inspection.get("username") or "")
        repos = inspection.get("repositories") or []
        usable = [r for r in repos if isinstance(r, dict) and not r.get("fork")
                  and not r.get("archived") and not r.get("disabled")
                  and _norm_name(r.get("name")) != _norm_name(owner)
                  and (_clean(r.get("description")) or r.get("languages") or r.get("topics"))]
        return usable, owner, ev.get("id"), ev.get("source_url")
    return [], "", None, None


def _github_verified_skills(evidence: List[dict]) -> List[dict]:
    """Canonical skills from GitHub verified signals (existing verification output)."""
    for ev in evidence or []:
        if str(ev.get("evidence_type") or "").lower() != "github" or ev.get("is_excluded"):
            continue
        signals = ((ev.get("metadata") or {}).get("verified_signals") or [])
        out = []
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            raw = sig.get("canonical_name") or sig.get("skill") or ""
            name = normalize_skill(str(raw)) or _clean(raw)
            if not name:
                continue
            meta = sig.get("metadata") if isinstance(sig.get("metadata"), dict) else {}
            definition = get_canonical_skill(name)
            out.append({"name": name,
                        "category": (definition.category if definition else "Technical Skills"),
                        "proficiency": None, "confidence": None, "evidence_count": 1,
                        "source": "github", "id": ev.get("id"),
                        "repo_count": int(meta.get("repo_count") or 0),
                        "signal_strength": float(sig.get("signal_strength") or sig.get("signal_value") or 0)})
        out.sort(key=lambda s: (-(s["repo_count"] or 0), -(s["signal_strength"] or 0), s["name"].lower()))
        return out
    return []


def _leetcode_stats(evidence: List[dict]) -> dict:
    for ev in evidence or []:
        if str(ev.get("evidence_type") or "").lower() != "leetcode" or ev.get("is_excluded"):
            continue
        inspection = ((ev.get("metadata") or {}).get("inspection") or {})
        def _int(value: Any) -> int:
            try:
                return max(int(value or 0), 0)
            except (TypeError, ValueError):
                return 0
        total = _int(inspection.get("total_solved"))
        easy, medium, hard = _int(inspection.get("easy_solved")), _int(inspection.get("medium_solved")), _int(inspection.get("hard_solved"))
        if total <= 0 and (easy + medium + hard) <= 0:
            return {}
        username = inspection.get("username") or ""
        return {"total": total or (easy + medium + hard), "easy": easy, "medium": medium,
                "hard": hard, "username": username, "url": ev.get("source_url") or "",
                "evidence_id": ev.get("id")}
    return {}


_RAW_TECH_STOPWORDS = frozenset({
    "languages", "language", "frameworks", "framework", "concepts", "concept", "tools", "tool",
    "interest", "interests", "stack", "and", "with", "using", "etc", "other", "including",
})


def _raw_doc_techs(text: Any) -> List[str]:
    """Raw technology tokens from a resume skills section that have no canonical mapping.

    These are the user's own words (e.g. EJS, Postman); kept verbatim and never
    mapped onto unrelated canonical skills.
    """
    tokens = re.split(r"[,/|\n:;]+", str(text or ""))
    out = []
    for token in tokens:
        cleaned = re.sub(r"\s+", " ", token).strip(" -–—()")
        if not cleaned or len(cleaned) > 24 or normalize_skill(cleaned):
            continue
        if cleaned.lower() in _RAW_TECH_STOPWORDS or len(cleaned) < 2:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out[:12]


def _doc_skill_names(skills_text: Any) -> List[str]:
    found = extract_known_skills_from_text(str(skills_text or ""))
    return [s.display_name for s in found]


def build_evidence_snapshot(user_id: str, target_role: str) -> dict:
    """Assemble the full evidence snapshot for a target role from existing services.

    Sources (all pre-existing, no parallel evidence system):
      profile <- profiles table (canonical fields only)
      manual projects <- projects table
      doc projects/experience/skills <- parsed resume/syllabus sections
      github repos + verified skills <- GitHub inspection / verified signals
      leetcode stats <- LeetCode inspection
      certifications <- certifications table
      assessed skills <- skill_assessments table
      requirements <- industry role benchmarks
    """
    requirements = _requirements(target_role)
    required = {normalize_skill(str(r.get("skill"))) for r in requirements if r.get("skill")}
    required.discard(None)
    profile = profile_service.get_profile(user_id) or {}
    projects = [p for p in evidence_service.list_projects(user_id) if not p.get("is_excluded")]
    certs = [c for c in evidence_service.list_certs(user_id) if not c.get("is_excluded")]
    evidence = [e for e in evidence_service.list_evidence(user_id) if not e.get("is_excluded")]
    assessed_skills = _load_skill_assessments(user_id)

    ranked = []
    for project in projects:
        score, matched = _project_score(project, required)
        ranked.append({"project": project, "score": score, "matched_skills": matched})
    ranked.sort(key=lambda x: (x["score"], len(_clean(x["project"].get("description")))), reverse=True)

    sections, doc_evidence_id = _doc_sections(evidence)
    doc_projects_raw = _parse_doc_projects(sections.get("projects"))
    doc_projects = []
    for entry in doc_projects_raw:
        techs = [s.display_name for s in extract_known_skills_from_text(
            f"{entry['title']} {' '.join(entry['bullets'])}")]
        overlap = [t for t in techs if t in required]
        doc_projects.append({"title": entry["title"], "bullets": entry["bullets"],
                             "technologies": techs, "matched_skills": overlap,
                             "score": len(overlap) * 4 + min(len(entry["bullets"]), 3),
                             "source_evidence_id": doc_evidence_id})
    doc_projects.sort(key=lambda x: (x["score"], len(x["bullets"])), reverse=True)

    repos, repo_owner, github_evidence_id, github_url = _github_repos(evidence)
    ranked_repos = []
    for repo in repos:
        score, matched = _repo_rank(repo, required)
        ranked_repos.append({"repo": repo, "score": score, "matched_skills": matched,
                             "technologies": _github_repo_techs(repo)})
    ranked_repos.sort(key=lambda x: (x["score"], str(x["repo"].get("name"))), reverse=True)

    exp_text = sections.get("experience") or sections.get("activities") or ""
    experience_entries, achievement_entries = _split_experience_achievements(exp_text)
    leetcode = _leetcode_stats(evidence)
    github_skills = _github_verified_skills(evidence)
    doc_skills_text = sections.get("skills") or ""
    doc_skill_names = _doc_skill_names(doc_skills_text)
    raw_doc_techs = _raw_doc_techs(doc_skills_text)

    # Grouped technical skills: role-relevant verified first, then other verified
    # skills, GitHub-demonstrated skills, and raw resume technologies. Canonical
    # names preserved; nothing restricted to the first few role skills.
    skills, seen = [], set()

    def _admit(name: str, category: str, source: str, ref_id: Any, extra: Optional[dict] = None) -> None:
        key = (normalize_skill(name) or name).lower()
        if not name or key in seen:
            return
        seen.add(key)
        item = {"name": normalize_skill(name) or name, "category": category or "Technical Skills",
                "proficiency": None, "confidence": None, "evidence_count": 1,
                "source": source, "id": ref_id}
        if extra:
            item.update(extra)
        skills.append(item)

    role_first = sorted(
        [s for s in assessed_skills if (normalize_skill(s["name"]) or s["name"]) in required],
        key=lambda item: (-(item.get("proficiency") or 0), -(item.get("confidence") or 0)))
    rest_assessed = sorted(
        [s for s in assessed_skills if (normalize_skill(s["name"]) or s["name"]) not in required],
        key=lambda item: (-(item.get("proficiency") or 0), -(item.get("confidence") or 0)))
    for skill in role_first + rest_assessed:
        definition = get_canonical_skill(skill["name"])
        _admit(skill["name"], skill.get("category") or (definition.category if definition else "Technical Skills"),
               "skill_assessment", skill.get("id"),
               {"proficiency": skill.get("proficiency"), "confidence": skill.get("confidence"),
                "evidence_count": skill.get("evidence_count")})
    for skill in github_skills:
        _admit(skill["name"], skill["category"], "github", skill.get("id"),
               {"repo_count": skill.get("repo_count")})
    for name in doc_skill_names:
        definition = get_canonical_skill(name)
        _admit(name, definition.category if definition else "Technical Skills", "resume", doc_evidence_id)
    for name in raw_doc_techs:
        _admit(name, "Technical Skills", "resume", doc_evidence_id)

    profile_fields = {k: profile.get(k) for k in (
        "full_name", "college", "degree", "branch", "current_year",
        "graduation_year", "career_interests", "preferred_work_location")}
    diagnostics = {
        "profile_fields_populated": sum(1 for v in profile_fields.values() if v not in (None, "", [], {})),
        "projects_considered": len(projects) + len(doc_projects_raw) + len(repos),
        "manual_projects": len(projects),
        "doc_projects_found": len(doc_projects_raw),
        "github_repos_considered": len(repos),
        "verified_skills_included": len(skills),
        "assessed_skills_loaded": len(assessed_skills),
        "certifications_included": len(certs),
        "experience_entries": len(experience_entries),
        "achievement_entries": len(achievement_entries) + (1 if leetcode else 0),
    }
    return {"profile": profile, "projects": ranked, "doc_projects": doc_projects,
            "github_repos": ranked_repos, "github_owner": repo_owner,
            "github_evidence_id": github_evidence_id, "github_url": github_url,
            "certifications": certs, "evidence": evidence, "skills": skills,
            "assessed_skills": assessed_skills, "github_skills": github_skills,
            "leetcode": leetcode, "experience": experience_entries,
            "achievements": achievement_entries, "doc_evidence_id": doc_evidence_id,
            "requirements": requirements, "target_role": canonicalize_role_name(target_role),
            "diagnostics": diagnostics}


def _header(snapshot: dict, contact_email: str | None = None) -> dict:
    """Header from canonical sources only: profile name, auth email, verified links.

    There is no canonical phone field in INAURA profiles, so phone stays empty
    instead of fabricated. Links come only from verified evidence source URLs.
    """
    profile = snapshot.get("profile") or {}
    links = []
    for ev in snapshot.get("evidence", []):
        kind = str(ev.get("evidence_type") or "").lower()
        url = _clean(ev.get("source_url"))
        if not url:
            continue
        label = {"github": "GitHub", "linkedin": "LinkedIn", "leetcode": "LeetCode",
                 "codeforces": "Codeforces", "kaggle": "Kaggle"}.get(kind)
        if label and not any(x["url"] == url for x in links):
            links.append({"label": label, "url": url})
    return {"name": _nonempty(profile.get("full_name")), "email": _clean(contact_email),
            "phone": "", "links": links}


def _education_entries(snapshot: dict) -> List[dict]:
    """All legitimate education fields from the canonical profile; omit when absent."""
    profile = snapshot.get("profile") or {}
    school = _nonempty(profile.get("college"))
    if not school and not any(profile.get(k) for k in ("degree", "branch", "graduation_year", "current_year")):
        return []
    entry = {"school": school, "degree": _nonempty(profile.get("degree")),
             "branch": _nonempty(profile.get("branch")),
             "current_year": _nonempty(profile.get("current_year")), "graduation_year": profile.get("graduation_year")}
    try:
        entry["graduation_year"] = int(entry["graduation_year"]) if entry["graduation_year"] not in (None, "") else None
    except (TypeError, ValueError):
        entry["graduation_year"] = None
    return [entry]


def _summary(snapshot: dict) -> str:
    """Role-targeted summary composed only from actual evidence pieces."""
    profile = snapshot.get("profile") or {}
    role = snapshot.get("target_role") or "software engineering"
    degree = _nonempty(profile.get("degree"))
    branch = _nonempty(profile.get("branch"))
    school = _nonempty(profile.get("college"))
    status = _nonempty(profile.get("current_year"))
    edu = " ".join(part for part in [degree, branch] if part)
    if edu and school:
        opener = f"{edu} student at {school}" + (f" ({status})" if status else "")
    elif edu or school:
        opener = f"{edu or school} student" + (f" ({status})" if status else "")
    else:
        opener = "Student"
    sentences = [f"{opener} targeting {role}."]
    prof_map = {s["name"]: (s.get("proficiency") or 0) for s in (snapshot.get("assessed_skills") or []) if s.get("name")}
    strengths = [name for name in prof_map if prof_map[name] > 0]
    strengths.sort(key=lambda n: (-prof_map[n], n.lower()))
    if strengths:
        sentences.append(f"Strongest verified areas include {', '.join(strengths[:4])}.")
    names = [p["project"].get("name") for p in (snapshot.get("projects") or [])[:2] if p["project"].get("name")]
    names += [p.get("title") for p in (snapshot.get("doc_projects") or [])[:2] if p.get("title")]
    names = list(dict.fromkeys(_clean(n) for n in names if _clean(n)))[:3]
    if names:
        sentences.append(f"Project experience includes {', '.join(names)}.")
    leetcode = snapshot.get("leetcode") or {}
    if leetcode.get("total"):
        parts = f"Solved {leetcode['total']} LeetCode problems"
        breakdown = ", ".join(f"{leetcode[k]} {label}" for k, label in
                              (("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")) if leetcode.get(k))
        sentences.append(f"{parts} ({breakdown})." if breakdown else f"{parts}.")
    return " ".join(sentences)


def _skill_groups(skills: list[dict]) -> dict:
    groups: dict[str, list[str]] = {}
    for skill in skills[:30]:
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        category = str(skill.get("category") or "Technical Skills")
        if name not in groups.setdefault(category, []):
            groups[category].append(name)
    return groups


def _manual_project_bullets(project: dict, matched: list[str]) -> list[str]:
    """Evidence-backed bullets: description, personal contribution, tech stack."""
    bullets = []
    description = _sentence(project.get("description"))
    if description:
        bullets.append(description)
    contribution = _sentence(project.get("student_contribution"))
    if contribution:
        bullets.append(contribution)
    techs = list(dict.fromkeys(
        ([normalize_skill(t) or str(t).strip() for t in (matched or [])]
         + [normalize_skill(str(t)) or str(t).strip() for t in (project.get("technologies") or [])])))
    techs = [t for t in techs if t][:6]
    if techs:
        bullets.append(f"Implemented using {', '.join(techs)}.")
    return bullets[:4]


def _github_repo_bullets(repo: dict, technologies: List[str]) -> list[str]:
    """Bullets from verified repository data: description + demonstrated languages."""
    bullets = []
    description = _sentence(repo.get("description"))
    if description:
        bullets.append(description)
    techs = [t for t in (technologies or []) if t][:4]
    if techs:
        bullets.append(f"Implemented using {', '.join(techs)}.")
    return bullets[:3]


def _project_bullets(project: dict, matched: list[str]) -> list[str]:
    return _manual_project_bullets(project, matched)


# ---------------------------------------------------------------------------
# Deterministic bullet-quality filter (no LLM).
#
# Applied at final per-project assembly, before claims are emitted, so
# content["projects"] bullets (UI + LaTeX) contain only resume-worthy claims
# while claims stay 1:1 with visible bullets. Filtered bullets are NOT
# deleted from evidence: the underlying snapshot/DB records are untouched,
# and each filtered bullet is recorded with its reason + anchors in
# content["_diagnostics"]["filtered_bullets"] for traceability.
# ---------------------------------------------------------------------------

_MARKETING_PHRASES = frozenset({
    "ultimate battle", "battle of wits", "outsmart", "super-smart", "super smart",
    "step into", "just another", "next level", "game-changer", "game changer",
    "cutting-edge", "cutting edge", "revolutionary", "mind-blowing", "mind blowing",
    "jaw-dropping", "jaw dropping", "unleash", "supercharge", "turbocharge",
    "blazing fast", "lightning fast", "seamless experience", "delightful",
    "magical experience", "epic", "insane", "crazy fast", "10x", "100x",
    "world-class", "world class", "best-in-class", "best in class", "can you beat",
})

_SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
    "|[🎮✨🚀🔥⭐🏆🎯💡👾🤖🎉]",
)
_TECH_ONLY_RE = re.compile(
    r"^(?:implemented|built|created|developed|made|written|crafted)\s+"
    r"(?:using|with|in|on)\s+(.+?)\.?$",
    re.I,
)
_GENERIC_BULLET_RE = re.compile(
    r"^(?:built|created|made|developed|worked on)\s+(?:a|an|the)\s+"
    r"(?:software\s+|web\s+|mobile\s+)?project\.?$",
    re.I,
)
_GENERIC_FALLBACKS = frozenset({
    "built and documented a software project",
})


def _bullet_tech_tokens(text: str) -> List[str]:
    match = _TECH_ONLY_RE.match(_clean(text))
    if not match:
        return []
    parts = re.split(r",|\band\b|&|\+", match.group(1), flags=re.I)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def _emoji_count(text: str) -> int:
    return len(_EMOJI_RE.findall(str(text or "")))


def _normalize_bullet_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", str(text or "").lower())).strip()


def classify_bullet(bullet: str, technologies: List[str] | None = None) -> tuple[bool, str]:
    """Deterministic keep/reject decision for one resume bullet.

    Returns (keep, reason). Reasons: "keep" when retained; otherwise one of
    redundant_tech_statement, marketing_prose, emoji_heavy, generic_claim,
    too_short. Duplicate detection is handled separately per project
    (needs sibling context) in filter_project_bullets().
    """
    text = _clean(bullet)
    if not text:
        return False, "empty"
    low = text.lower()

    # 1. Generic technology-only restatement, rejected only when every named
    # technology is already represented in the project's tech stack. A tech
    # statement naming unlisted technology carries new information: keep it
    # outright (it also bypasses the length check below by construction).
    tech_tokens = _bullet_tech_tokens(text)
    if tech_tokens:
        stack = {(normalize_skill(str(t)) or str(t)).lower() for t in (technologies or []) if str(t).strip()}
        mentioned = {(normalize_skill(tok) or tok).lower() for tok in tech_tokens}
        if mentioned and mentioned <= stack:
            return False, "redundant_tech_statement"
        return True, "keep"

    # 2. Marketing / promotional README prose.
    if any(phrase in low for phrase in _MARKETING_PHRASES):
        return False, "marketing_prose"
    if _SECOND_PERSON_RE.search(text) and ("!" in text or "?" in text or _emoji_count(text) >= 1):
        return False, "marketing_prose"

    # 3. Emoji-heavy feature-list text.
    if _emoji_count(text) >= 2:
        return False, "emoji_heavy"

    # 4. Very generic claims that communicate no concrete contribution.
    if _GENERIC_BULLET_RE.match(text) or low.rstrip(".") in _GENERIC_FALLBACKS:
        return False, "generic_claim"

    # 5. Fragments too short to carry a contribution.
    if len(text.split()) < 4:
        return False, "too_short"

    return True, "keep"


def filter_project_bullets(
    bullets: List[str],
    technologies: List[str] | None = None,
) -> tuple[List[str], List[dict]]:
    """Filter one project's candidate bullets deterministically.

    Preserves order; drops classifier rejects and near-duplicates (exact
    normalized match, or a shorter bullet fully contained in a kept longer
    bullet when the shorter carries >= 30 characters of its own). Returns
    (kept, filtered) where filtered entries carry {text, reason} for
    diagnostics traceability.
    """
    kept: List[str] = []
    kept_keys: List[str] = []
    filtered: List[dict] = []
    for bullet in bullets or []:
        text = _clean(bullet)
        if not text:
            continue
        keep, reason = classify_bullet(text, technologies)
        if not keep:
            filtered.append({"text": text, "reason": reason})
            continue
        key = _normalize_bullet_key(text)
        duplicate_of = None
        for existing_key in kept_keys:
            if key == existing_key:
                duplicate_of = existing_key
                break
            short, long = (key, existing_key) if len(key) <= len(existing_key) else (existing_key, key)
            if len(short) >= 30 and short in long:
                duplicate_of = existing_key
                break
        if duplicate_of is not None:
            filtered.append({"text": text, "reason": "duplicate_claim"})
            continue
        kept.append(text)
        kept_keys.append(key)
    return kept, filtered


def _resume_name_mismatch(snapshot: dict) -> bool:
    """Non-blocking diagnostic: uploaded resume name differs from canonical profile.

    Compares alpha token sets; reports a boolean flag only. Never overwrites
    the stored profile (the canonical source) and never blocks generation.
    """
    profile_name = _nonempty((snapshot.get("profile") or {}).get("full_name"))
    if not profile_name:
        return False

    def _tokens(value: Any) -> set[str]:
        return {w for w in re.split(r"[^a-z0-9]+", str(value or "").lower())
                if len(w) > 1 and w not in ("resume", "pdf", "doc", "docx", "curriculum", "vitae", "cv")}

    wanted = _tokens(profile_name)
    if not wanted:
        return False
    titles = []
    for ev in snapshot.get("evidence", []):
        if str(ev.get("evidence_type") or "").lower() not in ("resume",) or ev.get("is_excluded"):
            continue
        title = _clean(ev.get("title")) or _clean((ev.get("metadata") or {}).get("original_filename"))
        if title:
            titles.append(title)
    if not titles:
        return False
    return all(wanted.isdisjoint(_tokens(title)) for title in titles)


def deterministic_content(snapshot: dict, contact_email: str | None = None) -> tuple[dict, list[dict]]:
    profile = snapshot["profile"]
    content: Dict[str, Any] = {
        "header": _header(snapshot, contact_email),
        "summary": _summary(snapshot),
        "education": _education_entries(snapshot),
        "skills": [], "skill_groups": {}, "projects": [], "certifications": [],
        "experience": [], "achievements": [],
        "_diagnostics": dict(snapshot.get("diagnostics") or {}),
    }
    content["skills"] = [str(item.get("name")) for item in snapshot["skills"]]
    content["skill_groups"] = _skill_groups(snapshot["skills"])
    claims = []
    filtered_bullets: List[dict] = []

    def _claim(text: str, anchors: list[dict], prefix: str, index: int) -> None:
        claims.append({"claim_id": f"{prefix}:{index}", "text": text,
                       "status": "supported" if anchors else "needs_verification",
                       "evidence": anchors})

    def _record_filtered(items: List[dict], anchors: list[dict]) -> None:
        for item in items:
            filtered_bullets.append({"text": item["text"], "reason": item["reason"],
                                     "evidence": anchors})

    selected_names: set[str] = set()
    selected_titles: list[str] = []
    project_index = 0
    for item in (snapshot.get("projects") or [])[:4]:
        p = item["project"]
        name = _clean(p.get("name"))
        if not name:
            continue
        selected_names.add(_norm_name(name))
        selected_titles.append(name)
        raw_bullets = _manual_project_bullets(p, item.get("matched_skills") or [])
        links = [x for x in [p.get("github_url"), p.get("project_url")] if _clean(x)]
        techs = [str(t).strip() for t in (p.get("technologies") or []) if str(t).strip()]
        bullets, dropped = filter_project_bullets(raw_bullets, techs)
        if not bullets:
            continue
        content["projects"].append({"name": name, "technologies": techs,
                                    "description": _clean(p.get("description")),
                                    "bullets": bullets, "links": links})
        anchors = [{"type": "project", "id": p.get("id"), "name": name}]
        if p.get("github_url"):
            anchors.append({"type": "github", "url": p.get("github_url"), "name": name})
        _record_filtered(dropped, anchors)
        for i, bullet in enumerate(bullets):
            _claim(bullet, anchors, f"project:{p.get('id')}", project_index * 10 + i)
        project_index += 1

    doc_id = snapshot.get("doc_evidence_id")
    doc_candidates = []
    for entry in (snapshot.get("doc_projects") or [])[:4]:
        bullets = [b for b in (entry.get("bullets") or []) if b][:4]
        if not bullets:
            continue
        title = _clean(entry.get("title")) or "Project"
        doc_candidates.append({
            "title": title,
            "technologies": list(entry.get("technologies") or []),
            "bullets": bullets,
            "links": [],
            "anchors": ([{"type": "resume", "id": doc_id, "name": "Uploaded resume"}] if doc_id else []),
            "claim_prefix": f"doc-project:{_norm_name(title) or 'untitled'}",
        })

    github_candidates = []
    for item in (snapshot.get("github_repos") or [])[:5]:
        repo = item["repo"]
        slug = _clean(repo.get("name"))
        if not slug:
            continue
        display = humanize_repo_name(slug) or slug
        bullets = _github_repo_bullets(repo, item.get("technologies") or [])
        if not bullets:
            continue
        url = repo.get("html_url") or repo.get("url") or ""
        full_name = repo.get("full_name") or slug
        github_candidates.append({
            "title": display, "slug": slug, "repository": full_name,
            "technologies": list(item.get("technologies") or []),
            "bullets": bullets, "links": [url] if url else [],
            "anchors": [{"type": "github", "url": url or snapshot.get("github_url"),
                         "name": display, "repository": full_name}],
            "claim_prefix": f"github:{_norm_name(slug)}",
        })

    # Merge document + GitHub candidates on distinctive-token overlap so one
    # body of work (e.g. "AI-Based Tic-Tac-Toe" + repo "TIC-TAC-TOE") keeps a
    # single entry with the more informative title and combined provenance.
    merged = list(doc_candidates)
    for g in github_candidates:
        target = None
        for d in merged:
            if (_norm_name(g["slug"]) == _norm_name(d["title"])
                    or _likely_same_project(g["slug"], d["title"])
                    or _likely_same_project(g["title"], d["title"])):
                target = d
                break
        if target is None:
            merged.append({k: v for k, v in g.items() if k != "slug"})
            continue
        if len(g["title"]) > len(target["title"]):
            target["title"] = g["title"]
        for tech in g["technologies"]:
            if tech not in target["technologies"]:
                target["technologies"].append(tech)
        have = {b.lower() for b in target["bullets"]}
        for bullet in g["bullets"]:
            if bullet.lower() not in have:
                target["bullets"].append(bullet)
                have.add(bullet.lower())
        target["bullets"] = target["bullets"][:5]
        for url in g["links"]:
            if url and url not in target["links"]:
                target["links"].append(url)
        for anchor in g["anchors"]:
            if anchor not in target["anchors"]:
                target["anchors"].append(anchor)
        if g.get("repository"):
            target["repository"] = g["repository"]

    for entry in merged[:4]:
        if _norm_name(entry["title"]) in selected_names:
            continue
        if any(_likely_same_project(entry["title"], t) for t in selected_titles):
            continue
        selected_names.add(_norm_name(entry["title"]))
        selected_titles.append(entry["title"])
        bullets, dropped = filter_project_bullets(entry["bullets"], entry["technologies"] or [])
        if not bullets:
            _record_filtered(dropped, entry["anchors"])
            continue
        project = {"name": entry["title"], "technologies": entry["technologies"] or [],
                   "description": bullets[0],
                   "bullets": bullets, "links": entry.get("links") or []}
        if entry.get("repository"):
            project["repository"] = entry["repository"]
        content["projects"].append(project)
        _record_filtered(dropped, entry["anchors"])
        for i, bullet in enumerate(bullets):
            _claim(bullet, entry["anchors"], entry["claim_prefix"], i)

    for cert in snapshot["certifications"]:
        if not _clean(cert.get("name")):
            continue
        content["certifications"].append({"name": _clean(cert.get("name")),
                                          "issuing_org": _clean(cert.get("issuing_org")),
                                          "completion_year": cert.get("completion_year"),
                                          "url": _clean(cert.get("certificate_url"))})
    for entry in snapshot.get("experience", []):
        content["experience"].append({"text": entry,
                                      "source": "Uploaded resume" if doc_id else "Profile evidence"})
    for entry in snapshot.get("achievements", []):
        content["achievements"].append({"text": entry,
                                        "source": "Uploaded resume" if doc_id else "Profile evidence"})
    leetcode = snapshot.get("leetcode") or {}
    if leetcode.get("total"):
        breakdown = ", ".join(f"{leetcode[k]} {label}" for k, label in
                              (("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")) if leetcode.get(k))
        text = (f"Solved {leetcode['total']} LeetCode problems ({breakdown})."
                if breakdown else f"Solved {leetcode['total']} LeetCode problems.")
        content["achievements"].append({"text": text, "source": "LeetCode",
                                        "url": leetcode.get("url") or ""})
    content["_diagnostics"]["projects_selected"] = len(content["projects"])
    content["_diagnostics"]["filtered_bullets"] = filtered_bullets
    content["_diagnostics"]["profile_resume_name_mismatch"] = _resume_name_mismatch(snapshot)
    content["_diagnostics"]["sections_included"] = [k for k in
        ("summary", "education", "skills", "projects", "experience", "certifications", "achievements")
        if content.get(k)]
    return content, claims


def create_resume(user_id: str, target_role: str, title: str | None, template: str, contact_email: str | None = None) -> dict:
    snapshot = build_evidence_snapshot(user_id, target_role)
    content, claims = deterministic_content(snapshot, contact_email)
    payload = {"user_id": user_id, "title": title or f"{snapshot['target_role']} Resume", "target_role": snapshot["target_role"], "template": template, "content": content, "claims": claims}
    r = _client().table(TABLE).insert(payload).execute()
    return _row((r.data or [payload])[0])


def update_resume(user_id: str, resume_id: str, payload: dict) -> dict:
    get_resume(user_id, resume_id)
    r = _client().table(TABLE).update(payload).eq("user_id", user_id).eq("id", resume_id).execute()
    return _row((r.data or [])[0] if r.data else get_resume(user_id, resume_id))


def validate_resume_content(content: dict, snapshot: dict | None = None) -> None:
    content = content or {}
    missing = [field for field in ("header", "summary", "education") if not content.get(field)]
    if snapshot and snapshot.get("projects") and not content.get("projects"):
        missing.append("projects")
    if snapshot and snapshot.get("skills") and not content.get("skills"):
        missing.append("skills")
    if not content.get("projects") and not content.get("skills") and not content.get("experience"):
        missing.append("substantial content")
    if missing:
        raise HTTPException(422, "Resume generation returned incomplete content. Missing: " + ", ".join(dict.fromkeys(missing)) + ". Please regenerate.")


def verify_content(content: dict, claims: list[dict], snapshot: dict) -> dict:
    known = {str(normalize_skill(x.get("name")) or x.get("name")).lower() for x in snapshot.get("skills", [])}
    project_names = {str(p["project"].get("name", "")).lower() for p in snapshot.get("projects", [])}
    findings = []
    for section, values in content.items():
        if str(section).startswith("_"):
            continue  # internal diagnostics, not resume claims
        text = str(values)
        if not text.strip(): continue
        metrics = _METRIC_RE.findall(text)
        if metrics:
            findings.append({"section": section, "status": "needs_verification", "reason": "Metric claims require matching verified evidence.", "matches": metrics})
        unsupported = [word for word in re.findall(r"\b[A-Za-z][A-Za-z+#.-]{2,}\b", text) if str(normalize_skill(word) or word).lower() in {"python", "java", "react", "fastapi", "flutter", "android", "pytorch", "tensorflow"} and str(normalize_skill(word) or word).lower() not in known]
        if unsupported:
            findings.append({"section": section, "status": "needs_verification", "reason": "Technology is not present in demonstrated evidence.", "matches": unsupported})
    for claim in claims:
        if claim.get("status") == "supported" and claim.get("evidence"): findings.append({"claim_id": claim.get("claim_id"), "status": "supported", "reason": "Mapped to INAURA evidence."})
    return {"status": "needs_verification" if any(x["status"] == "needs_verification" for x in findings) else "supported", "findings": findings}


def latex_escape(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"([\\{}#$%&_])", r"\\\1", text).replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}").replace("—", "---")


def to_latex(resume: dict) -> str:
    c = resume.get("content") or {}; h = c.get("header") or {}
    validate_resume_content(c)
    out = [r"\documentclass[10pt,a4paper]{article}", r"\usepackage[utf8]{inputenc}", r"\usepackage[T1]{fontenc}", r"\usepackage[margin=0.65in]{geometry}", r"\usepackage[hidelinks]{hyperref}", r"\usepackage{enumitem}", r"\pagenumbering{gobble}", r"\begin{document}", r"\begin{center}", f"{{\\LARGE \\textbf{{{latex_escape(h.get('name'))}}}}}\\\\", r"\end{center}"]
    contact = [h.get("email"), h.get("phone")]
    contact += [f"\\href{{{latex_escape(link.get('url'))}}}{{{latex_escape(link.get('label') or link.get('url'))}}}" for link in h.get("links") or [] if link.get("url")]
    if any(contact):
        out.append(" \\textbar{} ".join(latex_escape(value) if not str(value).startswith("\\href") else str(value) for value in contact if value))
    if c.get("summary"): out += [r"\section*{Summary}", latex_escape(c["summary"])]
    if c.get("skills"):
        out.append(r"\section*{Skills}")
        groups = c.get("skill_groups") or {"Technical Skills": c["skills"]}
        out += [f"\\textbf{{{latex_escape(category)}}}: {latex_escape(', '.join(values))}\\\\" for category, values in groups.items()]
    if c.get("education"):
        out.append(r"\section*{Education}")
        for e in c["education"]: out.append(f"\\textbf{{{latex_escape(e.get('school'))}}} — {latex_escape(e.get('degree'))} {latex_escape(e.get('branch'))} ({latex_escape(e.get('graduation_year'))})\\\\")
    if c.get("projects"):
        out.append(r"\section*{Projects}")
        for p in c["projects"]:
            out += [f"\\textbf{{{latex_escape(p.get('name'))}}} — {latex_escape(', '.join(p.get('technologies') or []))}", r"\begin{itemize}[leftmargin=*]"]
            if p.get("links"):
                out.append("Links: " + " ".join(f"\\href{{{latex_escape(url)}}}{{link}}" for url in p.get("links") or []))
            out += [f"\\item {latex_escape(b)}" for b in p.get("bullets") or []] + [r"\end{itemize}"]
    if c.get("certifications"):
        out.append(r"\section*{Certifications}")
        out += [f"{latex_escape(x.get('name'))} — {latex_escape(x.get('issuing_org'))} ({latex_escape(x.get('completion_year'))})\\\\" for x in c["certifications"]]
    out += [r"\end{document}"]
    out = [line.replace("\u2014", "---").replace("â€”", "---").replace("�", "---") for line in out]
    return "\n".join(out)
