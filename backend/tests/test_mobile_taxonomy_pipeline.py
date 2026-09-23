import asyncio

from app.services import industry_service, retrieval_service
from app.services.industry_roles import canonicalize_role_name
from app.services.skill_taxonomy import (
    audit_taxonomy_consistency,
    normalize_skill,
    normalize_skill_slug,
    RAW_TAXONOMY,
)


def test_mobile_role_aliases_and_phrase_normalization():
    for value in ("app developer", "flutter developer", "ios developer", "android developer"):
        assert canonicalize_role_name(value) == "Mobile Developer"
    assert normalize_skill("Flutter") == "Flutter"
    assert normalize_skill("flutter development") == "Flutter"
    assert normalize_skill_slug("flutter developer") == "flutter"
    assert normalize_skill_slug("React Native") == "react_native"
    assert normalize_skill_slug("iOS") == "ios"


def test_mobile_requirements_are_canonical_and_provenanced():
    rows = industry_service.list_by_role("Mobile Developer")
    skills = {row["skill_slug"] for row in rows}
    assert {"flutter", "android", "ios", "react_native"}.issubset(skills)
    for row in rows:
        assert row["skill"] == normalize_skill(row["skill"])
        assert row["source"] and row["source_url"]
        assert row["source_version"] and row["source_reference"]
        assert row["mapping_version"] and row["role_relevance"]
        assert row["source_concept"] and row["canonical_mapping"]


def test_mobile_query_retrieval_surfaces_frameworks():
    for query in ("mobile development", "app development", "flutter development", "mobile developer"):
        result = asyncio.run(retrieval_service.retrieve("Mobile Developer", query=query, top_k=10))
        skills = {normalize_skill_slug(item["skill"]) for item in result["items"]}
        assert {"flutter", "android", "ios", "react_native"}.issubset(skills)


def test_app_intent_is_role_gated():
    result = asyncio.run(retrieval_service.retrieve("Backend Developer", query="web app development", top_k=10))
    skills = {normalize_skill_slug(item["skill"]) for item in result["items"]}
    assert "flutter" not in skills
    assert "react_native" not in skills


def test_taxonomy_audit_detects_missing_database_rows():
    report = audit_taxonomy_consistency(
        database_skills=[{"canonical_name": "flutter"}],
        role_requirements=[{"skill": "Flutter"}],
    )
    assert "android" in report["missing_database_skills"]
    assert report["invalid_role_requirements"] == []
    assert report["canonical_count"] == len(RAW_TAXONOMY)
