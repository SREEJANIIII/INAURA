import pytest
import io
import asyncio
from app.services import ats_service
from app.services import document_parser as dp


def _make_sample_resume_bytes() -> bytes:
    content = """
Alex Morgan
Email: alex.morgan@example.com | Phone: +1-555-019-2834 | San Francisco, CA
LinkedIn: linkedin.com/in/alexmorgan-dev | GitHub: github.com/alexmorgan

PROFESSIONAL SUMMARY
Results-driven Software Engineer with 3+ years of experience building scalable backend architectures and distributed microservices.

TECHNICAL SKILLS
Languages: Python, JavaScript, SQL
Frameworks: FastAPI, Django, React
Databases: PostgreSQL, Redis
Tools & Practices: Git, Docker, Automated Testing, Linux

WORK EXPERIENCE
Senior Backend Developer | TechFlow Inc.
2022 - Present
- Architected and deployed 15 RESTful microservices using Python and FastAPI, reducing API latency by 45% for 120k daily active users.
- Optimized PostgreSQL queries and implemented indexing strategies, saving $12,000 in annual AWS cloud database infrastructure costs.
- Engineered automated CI/CD pipelines using Docker and GitHub Actions, expediting code deployment turnaround by 3x.
- Spearheaded database schema redesign supporting 5M+ transaction records with zero downtime.

Software Engineer Intern | Innovate Labs
2021 - 2022
- Developed responsive web interfaces using React and integrated REST APIs.
- Collaborated with 6 engineers in agile sprint cycles and resolved 40+ production bug tickets.

EDUCATION
Bachelor of Science in Computer Science | University of California, Berkeley
Graduated: May 2022 | GPA: 3.8

PROJECTS
Cloud Storage Engine
- Built a distributed key-value storage engine in Python supporting concurrent reads with sub-50ms latency.
"""
    return content.strip().encode("utf-8")


def test_get_supported_ats_roles():
    roles = ats_service.get_supported_ats_roles()
    assert len(roles) >= 11
    titles = {r.title for r in roles}
    assert "Software Engineer" in titles
    assert "Backend Developer" in titles
    assert "Frontend Developer" in titles
    backend_role = next(r for r in roles if r.title == "Backend Developer")
    assert len(backend_role.benchmark_skills) > 0


def test_ats_scanner_evaluation():
    sample_bytes = _make_sample_resume_bytes()
    result = asyncio.run(ats_service.test_resume_ats(
        file_bytes=sample_bytes,
        filename="alex_morgan_resume.txt",
        target_role="Backend Developer",
        job_description=None,
    ))

    # Validate high-level fields
    assert result.target_role == "Backend Developer"
    assert result.word_count > 150
    assert result.scores.overall >= 70
    assert result.scores.skills_match >= 60
    assert result.scores.impact_metrics >= 60
    assert result.scores.sections_structure >= 80
    assert result.scores.formatting_parseability >= 80

    # Contact checks
    assert result.contact.has_email is True
    assert "alex.morgan@example.com" in (result.contact.email or "")
    assert result.contact.has_phone is True
    assert result.contact.has_linkedin is True
    assert result.contact.has_github is True

    # Matched skills
    matched_skill_names = {m.skill for m in result.matched_skills}
    assert "Python" in matched_skill_names
    assert "PostgreSQL" in matched_skill_names or "SQL" in matched_skill_names
    assert "REST APIs" in matched_skill_names or "FastAPI" in matched_skill_names

    # Action verbs & metrics
    assert len(result.action_verbs_found) >= 5
    assert "architected" in [v.lower() for v in result.action_verbs_found]
    assert len(result.metrics_found) >= 3

    # Recommendations
    assert len(result.recommendations) > 0

    # Sections
    sec_names = {s.name for s in result.sections if s.found}
    assert "Contact Information" in sec_names
    assert "Technical / Core Skills" in sec_names
    assert "Experience / Work History" in sec_names
    assert "Education" in sec_names


def test_ats_scanner_role_difference():
    sample_bytes = _make_sample_resume_bytes()
    # Test for Data Analyst where resume doesn't focus as much
    result = asyncio.run(ats_service.test_resume_ats(
        file_bytes=sample_bytes,
        filename="alex_morgan_resume.txt",
        target_role="Data Analyst",
    ))
    # Missing skills should contain data-analyst specific skills like Pandas or Statistics or Data Visualization
    missing = {m.skill for m in result.missing_skills}
    assert any(s in missing for s in ["Pandas", "Data Visualization", "Statistics"])


def test_ats_empty_resume_raises():
    with pytest.raises(Exception):
        asyncio.run(ats_service.test_resume_ats(
            file_bytes=b"",
            filename="empty.pdf",
            target_role="Software Engineer",
        ))


def test_ats_contact_info_handles_and_portfolio():
    raw_text = (
        "Jane Doe\n"
        "Email: jane.doe@techcorp.dev\n"
        "Phone: +91 98765 43210\n"
        "Portfolio: https://janedoe.me\n"
        "LinkedIn: https://linkedin.com/in/janedoe\n"
        "GitHub: github.com/janedoe\n"
    )
    doc_links = [
        "https://janedoe.me",
        "https://linkedin.com/in/janedoe",
        "https://github.com/janedoe",
        "mailto:jane.doe@techcorp.dev",
        "https://leetcode.com/janedoe",
    ]
    contact = ats_service._extract_contact_info(raw_text, doc_links)
    assert contact.has_email is True
    assert contact.email == "jane.doe@techcorp.dev"
    assert contact.has_phone is True
    assert "+91 98765 43210" in (contact.phone or "")
    assert contact.has_linkedin is True
    assert "janedoe" in (contact.linkedin_url or "")
    assert contact.has_github is True
    assert "janedoe" in (contact.github_url or "")
    assert contact.has_portfolio is True
    assert "janedoe.me" in (contact.portfolio_url or "")
    assert len(contact.all_links) >= 4
    assert any("leetcode.com" in l for l in contact.all_links)


def test_ats_contact_info_labeled_and_grouped_phone():
    # Test labeled phone, grouped phone, spaced email
    raw_text = (
        "Candidate Name\n"
        "Contact No: +91 98765 43210\n"
        "E-mail: candidate.work @ tech.io\n"
        "GitHub: github.com/candidatedev\n"
    )
    contact = ats_service._extract_contact_info(raw_text, [])
    assert contact.has_email is True
    assert contact.email == "candidate.work@tech.io"
    assert contact.has_phone is True
    assert "98765 43210" in (contact.phone or "")
    assert contact.has_github is True


def test_ats_endpoint_rejects_non_docx():
    from app.api.v1.endpoints.resume import test_resume_ats_endpoint
    from fastapi import UploadFile, HTTPException
    from unittest.mock import MagicMock

    current_user = MagicMock(id="user123")
    fake_pdf = UploadFile(
        filename="resume.pdf",
        file=io.BytesIO(b"fake pdf content"),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(test_resume_ats_endpoint(
            target_role="Software Engineer",
            job_description=None,
            evidence_id=None,
            file=fake_pdf,
            current_user=current_user,
        ))
    assert exc_info.value.status_code == 400
    assert ".docx" in exc_info.value.detail


