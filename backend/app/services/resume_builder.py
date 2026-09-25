"""Evidence-backed resume assembly, verification, and LaTeX export."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from . import evidence_service, industry_service, profile_service
from .industry_roles import canonicalize_role_name
from .skill_taxonomy import normalize_skill

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


def _project_score(project: dict, required: set[str]) -> tuple[int, list[str]]:
    techs = [str(x).strip() for x in (project.get("technologies") or []) if str(x).strip()]
    matched = [x for x in techs if normalize_skill(x) in required]
    score = len(matched) * 3 + (2 if project.get("github_url") else 0) + (1 if project.get("project_url") else 0)
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


def build_evidence_snapshot(user_id: str, target_role: str) -> dict:
    requirements = _requirements(target_role)
    required = {normalize_skill(str(r.get("skill"))) for r in requirements if r.get("skill")}
    profile = profile_service.get_profile(user_id) or {}
    projects = [p for p in evidence_service.list_projects(user_id) if not p.get("is_excluded")]
    certs = [c for c in evidence_service.list_certs(user_id) if not c.get("is_excluded")]
    evidence = [e for e in evidence_service.list_evidence(user_id) if not e.get("is_excluded")]
    assessed_skills = _load_skill_assessments(user_id)
    ranked = []
    for project in projects:
        score, matched = _project_score(project, required)
        ranked.append({"project": project, "score": score, "matched_skills": matched})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    skills = []
    seen = set()
    for skill in sorted(assessed_skills, key=lambda item: (item["name"].lower() not in required, -item["proficiency"], -item["confidence"])):
        if normalize_skill(skill["name"]) in required and skill["name"].lower() not in seen:
            skills.append(skill); seen.add(skill["name"].lower())
    for item in ranked:
        for tech in item["project"].get("technologies") or []:
            key = normalize_skill(str(tech))
            if key in required and key not in seen:
                skills.append({"name": str(tech), "category": "Technical Skills", "proficiency": None, "confidence": None,
                               "evidence_count": 1, "source": "project", "id": item["project"].get("id")}); seen.add(key)
    # Skills are only admitted from demonstrated project/evidence data or persisted assessments.
    return {"profile": profile, "projects": ranked, "certifications": certs, "evidence": evidence,
            "skills": skills, "assessed_skills": assessed_skills,
            "requirements": requirements, "target_role": canonicalize_role_name(target_role)}


def _bullet(project: dict, matched: list[str]) -> str:
    desc = re.sub(r"\s+", " ", str(project.get("description") or "").strip()).rstrip(".")
    tech = ", ".join(matched[:4])
    if tech:
        return f"Built {desc[0].lower() + desc[1:] if desc else 'a software project'} using {tech}."
    return f"Built {desc[0].lower() + desc[1:] if desc else 'a software project'}."


def deterministic_content(snapshot: dict, contact_email: str | None = None) -> tuple[dict, list[dict]]:
    profile = snapshot["profile"]
    projects = snapshot["projects"][:4]
    content: Dict[str, Any] = {
        "header": {"name": profile.get("full_name", ""), "email": contact_email or profile.get("email", ""), "phone": profile.get("phone", ""), "links": []},
        "summary": _summary(snapshot),
        "education": [{"school": profile.get("college", ""), "degree": profile.get("degree", ""), "branch": profile.get("branch", ""), "graduation_year": profile.get("graduation_year")}],
        "skills": [str(item.get("name")) for item in snapshot["skills"]], "skill_groups": _skill_groups(snapshot["skills"]), "projects": [], "certifications": [], "experience": [], "achievements": []
    }
    links = []
    for ev in snapshot.get("evidence", []):
        url = ev.get("source_url")
        kind = str(ev.get("evidence_type") or "").lower()
        if url and kind in {"github", "linkedin"} and not any(x["url"] == url for x in links):
            links.append({"label": "GitHub" if kind == "github" else "LinkedIn", "url": url})
    content["header"]["links"] = links
    claims = []
    for item in projects:
        p = item["project"]
        bullets = _project_bullets(p, item["matched_skills"])
        content["projects"].append({"name": p.get("name", ""), "technologies": p.get("technologies") or [], "description": p.get("description", ""), "bullets": bullets,
                                     "links": [x for x in [p.get("github_url"), p.get("project_url")] if x]})
        for i, bullet in enumerate(bullets):
            anchors = [{"type": "project", "id": p.get("id"), "name": p.get("name")}]
            if p.get("github_url"): anchors.append({"type": "github", "url": p.get("github_url"), "name": p.get("name")})
            claims.append({"claim_id": f"project:{p.get('id')}:{i}", "text": bullet, "status": "supported", "evidence": anchors})
    for cert in snapshot["certifications"]:
        content["certifications"].append({"name": cert.get("name", ""), "issuing_org": cert.get("issuing_org", ""), "completion_year": cert.get("completion_year"), "url": cert.get("certificate_url")})
    return content, claims


def _summary(snapshot: dict) -> str:
    names = [str(item.get("name")) for item in snapshot.get("skills", [])[:5] if item.get("name")]
    role = snapshot.get("target_role") or "software engineering"
    if names:
        return f"Software engineering student targeting {role}, with hands-on experience building projects using {', '.join(names)}."
    return f"Software engineering student targeting {role}, with hands-on experience building software projects."


def _skill_groups(skills: list[dict]) -> dict:
    groups: dict[str, list[str]] = {}
    for skill in skills[:18]:
        groups.setdefault(str(skill.get("category") or "Technical Skills"), []).append(str(skill.get("name")))
    return groups


def _project_bullets(project: dict, matched: list[str]) -> list[str]:
    bullets = []
    description = re.sub(r"\s+", " ", str(project.get("description") or "").strip()).rstrip(".")
    if description:
        bullets.append(f"Built {description[0].lower() + description[1:] if description else description}.")
    contribution = re.sub(r"\s+", " ", str(project.get("student_contribution") or "").strip()).rstrip(".")
    if contribution:
        bullets.append(f"{contribution[0].upper() + contribution[1:] }.")
    elif matched:
        bullets.append(f"Implemented the project using {', '.join(matched[:5])}.")
    return bullets[:3] or ["Built and documented a software project."]


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
