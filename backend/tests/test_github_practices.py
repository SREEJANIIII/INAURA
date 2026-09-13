"""
Phase 10: GitHub engineering-practice analysis tests.

Verifies the SEPARATE practices dimension: deterministic per-dimension
scoring from observable evidence, provenance on every finding, confidence
levels, explainable reasons, and strict isolation from technical skill
proficiency and readiness (no score mixing, no pipeline version bump).

Conceptual framing (no overclaim):
"INAURA performs repository-level code and artifact inspection to extract
evidence of demonstrated technical skills." Practices describe OBSERVED
repository behavior only -- static inspection never certifies quality or
security, and absence of findings proves nothing.
"""

import asyncio
import json
from datetime import datetime, timezone

from app.services.evidence.base import EVIDENCE_PIPELINE_VERSION, EvidenceDepth
from app.services.evidence.engineering_practices import (
    DIMENSIONS,
    MODEL_VERSION,
    aggregate_practices,
    analyze_engineering_practices,
    detect_ci_test_steps,
    detect_error_handling,
    merge_error_counts,
    summarize_practices,
)
from app.services.evidence.github import (
    GitHubProvider,
    compact_inspection,
)
from app.services import skill_engine


def _run(coro):
    return asyncio.run(coro)


def _repo_meta(owner, name, **overrides):
    meta = {
        "id": abs(hash(name)) % 10_000_000,
        "name": name,
        "full_name": f"{owner}/{name}",
        "html_url": f"https://github.com/{owner}/{name}",
        "description": "",
        "language": None,
        "fork": False,
        "archived": False,
        "disabled": False,
        "size": 2500,
        "default_branch": "main",
        "topics": [],
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "stargazers_count": 0,
    }
    meta.update(overrides)
    return meta


def _inspection_repo(owner, name, inspection, **meta):
    base = _repo_meta(owner, name, **meta)
    base["inspection"] = inspection
    return base


def _direct(owner, repo, inspection):
    return GitHubProvider()._build_result_from_inspection(
        owner, repo, inspection, datetime.now(timezone.utc)
    )


def _fullstack_inspection(**overrides):
    """A well-engineered reference repository exercising every dimension."""
    inspection = {
        "name": "svc",
        "full_name": "dev/svc",
        "description": "Example service",
        "languages": {"Python": 40000},
        "root_files": ["requirements.txt", "Dockerfile", "README.md",
                       ".gitignore", ".env.example", "package.json", ".dockerignore"],
        "top_files": ["src/app.py", "src/services/billing.py", "src/models/user.py",
                      "src/api/routes.py", "tests/test_billing.py", "tests/test_api.py",
                      "docs/guide.md", "CHANGELOG.md", ".github/workflows/ci.yml",
                      ".github/workflows/release.yml",
                      "docker-compose.yml", "openapi.yaml", "src/api/v1/users.py",
                      "pytest.ini", "ruff.toml"],
        "package_json_deps": ["react"],
        "python_deps": ["fastapi", "pytest", "pyjwt"],
        "eco_manifest_deps": [],
        "eco_python_deps": [],
        "ext_file_counts": {".py": 6},
        "has_workflows": True,
        "has_ci_config": False,
        "has_k8s_manifests": False,
        "k8s_manifest_count": 0,
        "tree_scanned": True,
        "readme_path": "README.md",
        "readme_text": "# Service\n\n" + "A well documented service. " * 60,
        "source_files_sampled": ["src/app.py", "src/services/billing.py"],
        "import_tokens": {"fastapi": 3, "pytest": 1},
        "usage_patterns": {
            "REST APIs": {"fastapi_app": 2, "route_decorator": 1},
            "Testing": {"test_import": 1},
        },
        "usage_files": {
            "REST APIs": ["src/app.py", "src/api/routes.py"],
            "Testing": ["tests/test_billing.py"],
        },
        "config_files_sampled": ["Dockerfile", ".github/workflows/ci.yml"],
        "config_text": ("FROM python:3.11-slim AS base\n"
                        "USER appuser\n"
                        "RUN pip install -r requirements.txt\n"
                        "RUN pytest -q\n"),
        "error_indicators": {"try_blocks": 2, "handlers": 2, "raise_throw": 1,
                             "validation": 1, "error_responses": 1},
        "error_files": {
            "try_blocks": ["src/services/billing.py"],
            "handlers": ["src/services/billing.py"],
            "raise_throw": ["src/api/routes.py"],
            "validation": ["src/models/user.py"],
            "error_responses": ["src/api/routes.py"],
        },
        "test_file_count": 2,
    }
    inspection.update(overrides)
    return inspection


def _dim(report, name):
    return report["dimensions"][name]


# ---------------------------------------------------------------------------
# Error-handling detection units
# ---------------------------------------------------------------------------

def test_detect_error_handling_python():
    text = ("try:\n    risky()\nexcept ValueError as e:\n    raise RuntimeError(e)\n"
            "from pydantic import BaseModel\n")
    hits = detect_error_handling(text)
    assert hits.get("try_blocks", 0) >= 1
    assert hits.get("handlers", 0) >= 1
    assert hits.get("raise_throw", 0) >= 1
    assert hits.get("validation", 0) >= 1


def test_detect_error_handling_javascript_and_go():
    js = "try {\n  await run();\n} catch (err) {\n  throw new Error('x');\n}"
    hits = detect_error_handling(js)
    assert hits.get("try_blocks", 0) >= 1
    assert hits.get("handlers", 0) >= 1
    assert hits.get("raise_throw", 0) >= 1
    go = 'data, err := load()\nif err != nil {\n  return err\n}\n'
    hits_go = detect_error_handling(go)
    assert hits_go.get("handlers", 0) >= 1
    assert "try_blocks" not in hits_go


def test_detect_error_handling_ignores_comments_and_strings():
    text = ('# try: this is just a comment\n'
            '# except ValueError: also a comment\n'
            'note = "try this at home; raise no errors"\n'
            'x = 1\n')
    assert detect_error_handling(text) == {}
    assert detect_error_handling("") == {}
    assert detect_error_handling("   \n  ") == {}


def test_merge_error_counts_accumulates_files():
    counts: dict = {}
    files: dict = {}
    merge_error_counts(counts, files, {"try_blocks": 2}, "src/a.py")
    merge_error_counts(counts, files, {"try_blocks": 1}, "src/b.py")
    assert counts == {"try_blocks": 3}
    assert sorted(files["try_blocks"]) == ["src/a.py", "src/b.py"]


def test_detect_ci_test_steps():
    assert detect_ci_test_steps("steps:\n  - run: pytest -q\n") == ["pytest"]
    assert detect_ci_test_steps("run: npm test\n") == ["npm test"]
    assert detect_ci_test_steps("run: ./gradlew test\n") == ["./gradlew test"]
    assert detect_ci_test_steps("name: build\nrun: echo hi\n") == []
    assert detect_ci_test_steps("") == []
    # No substring false positives: "pytester" tooling is not pytest.
    assert "pytest" not in detect_ci_test_steps("run: pytester --check\n")


# ---------------------------------------------------------------------------
# Dimension presence, scoring math, and confidence levels
# ---------------------------------------------------------------------------

def test_all_ten_dimensions_always_present():
    report = analyze_engineering_practices({})
    assert report["version"] == MODEL_VERSION
    assert list(report["dimensions"].keys()) == list(DIMENSIONS)
    assert len(report["dimensions"]) == 10
    for dim in DIMENSIONS:
        entry = report["dimensions"][dim]
        assert entry["score"] == 0.0
        assert entry["present"] is False
        assert entry["confidence"] == "low"
        assert entry["reason"]
    # Stable schema: all dimensions reported absent, summary says so explicitly.
    assert "no evidence observed" in report["summary"]
    assert summarize_practices({}) == "No engineering-practice evidence analyzed."
    assert summarize_practices(None) == "No engineering-practice evidence analyzed."


def test_testing_full_marks_and_confidence():
    report = analyze_engineering_practices(_fullstack_inspection())
    testing = _dim(report, "testing")
    assert testing["score"] == 1.0
    assert testing["confidence"] == "high"
    assert testing["present"] is True
    assert "test" in testing["reason"].lower()


def test_testing_partial_scores_and_confidence_progression():
    base = _fullstack_inspection(
        top_files=["src/app.py"],
        test_file_count=0,
        python_deps=["fastapi"],
        usage_patterns={},
        usage_files={},
        config_text="",
        config_files_sampled=[],
    )
    # No testing evidence at all.
    assert _dim(analyze_engineering_practices(base), "testing")["score"] == 0.0
    # Files only -> 0.40, single indicator -> low confidence.
    files_only = dict(base, top_files=["src/app.py", "tests/test_app.py"], test_file_count=1)
    partial = _dim(analyze_engineering_practices(files_only), "testing")
    assert partial["score"] == 0.40
    assert partial["confidence"] == "low"
    # Files + framework -> 0.70, two indicators -> medium confidence.
    plus_fw = dict(files_only, python_deps=["fastapi", "pytest"])
    stronger = _dim(analyze_engineering_practices(plus_fw), "testing")
    assert stronger["score"] == 0.70
    assert stronger["confidence"] == "medium"


def test_error_handling_dimension_and_confidence():
    report = analyze_engineering_practices(_fullstack_inspection())
    entry = _dim(report, "error_handling")
    # try/except + raise + validation + responses = full marks, high confidence.
    assert entry["score"] == 1.0
    assert entry["confidence"] == "high"
    # vendored error files never count.
    vendored = _fullstack_inspection(error_files={
        "try_blocks": ["node_modules/pkg/index.js"],
        "handlers": ["node_modules/pkg/index.js"],
    })
    assert _dim(analyze_engineering_practices(vendored), "error_handling")["present"] is False


def test_security_never_claims_guarantees_and_caps_confidence():
    report = analyze_engineering_practices(_fullstack_inspection())
    sec = _dim(report, "security_practices")
    assert sec["score"] == 1.0  # all four indicators observed
    assert sec["confidence"] == "medium"  # capped: static inspection cannot verify posture
    assert "cannot" in sec["reason"] and "guarantee" in sec["reason"]
    assert "guarantee security" not in sec["reason"].lower().replace("cannot guarantee", "")
    # No overclaim vocabulary anywhere in the report.
    blob = json.dumps(report).lower()
    assert "guaranteed secure" not in blob
    assert "no vulnerabilities" not in blob


def test_dependency_management_lockfiles():
    only_manifest = _fullstack_inspection(
        root_files=["requirements.txt"], top_files=["app.py"],
        python_deps=["fastapi"], package_json_deps=[],
    )
    entry = _dim(analyze_engineering_practices(only_manifest), "dependency_management")
    assert entry["score"] == 0.70  # 0.50 manifest + 0.20 parsed deps
    assert "lockfiles" in entry["reason"]  # missing indicator is named
    with_lock = dict(only_manifest, root_files=["requirements.txt", "package-lock.json"])
    locked = _dim(analyze_engineering_practices(with_lock), "dependency_management")
    assert locked["score"] == 1.0


def test_containerization_progression():
    base = _fullstack_inspection(
        root_files=["README.md"], top_files=["src/app.py"],
        config_text="", config_files_sampled=[],
    )
    assert _dim(analyze_engineering_practices(base), "containerization")["score"] == 0.0
    docker_only = dict(base, root_files=["Dockerfile"], top_files=["Dockerfile", "src/app.py"])
    assert _dim(analyze_engineering_practices(docker_only), "containerization")["score"] == 0.40
    full = _fullstack_inspection()
    full_ci = _dim(analyze_engineering_practices(full), "containerization")
    assert full_ci["score"] == 1.0
    assert full_ci["confidence"] == "high"


def test_project_structure_api_design_maintainability():
    report = analyze_engineering_practices(_fullstack_inspection())
    struct = _dim(report, "project_structure")
    assert struct["present"] is True
    assert struct["score"] >= 0.85  # src layout + tests dir + layered + breadth
    api = _dim(report, "api_design")
    assert api["present"] is True
    assert api["score"] >= 0.50  # route patterns observed
    assert any("openapi" in f.lower() for f in
               next(f["files"] for f in api["findings"] if f["indicator"] == "openapi_spec"))
    docs = _dim(report, "documentation")
    assert docs["score"] >= 0.60  # README + length + docs dir
    assert docs["confidence"] in ("medium", "high")
    ci = _dim(report, "ci_cd")
    assert ci["score"] == 1.0  # workflows + multiple workflow files + test step
    maint = _dim(report, "code_maintainability")
    assert maint["present"] is True
    assert maint["score"] >= 0.65  # lint config + modular breadth
    assert maint["confidence"] == "medium"


# ---------------------------------------------------------------------------
# Provenance, explainability, and compactness
# ---------------------------------------------------------------------------

def test_every_finding_has_provenance():
    report = analyze_engineering_practices(_fullstack_inspection())
    for dim in DIMENSIONS:
        entry = report["dimensions"][dim]
        assert entry["reason"], dim
        for finding in entry["findings"]:
            assert finding["indicator"], dim
            assert isinstance(finding["present"], bool), dim
            assert finding["detail"], dim
            assert isinstance(finding["files"], list), dim


def test_no_source_contents_stored():
    sentinel = "SENTINEL-UNIQUE-README-BODY-9f8e7d6c5b4a"
    inspection = _fullstack_inspection(
        readme_text=sentinel * 40,
        config_text="SENTINEL-CONFIG-BODY-1234567890 " * 20,
    )
    report = analyze_engineering_practices(inspection)
    blob = json.dumps(report)
    assert sentinel not in blob
    assert "SENTINEL-CONFIG-BODY" not in blob
    assert len(blob) < 20000


def test_summary_explains_results():
    report = analyze_engineering_practices(_fullstack_inspection())
    assert isinstance(report["summary"], str) and report["summary"]
    assert "testing" in report["summary"]
    empty = analyze_engineering_practices({})
    assert "no evidence" in empty["summary"].lower()


def test_deterministic_repeated_analysis():
    first = analyze_engineering_practices(_fullstack_inspection())
    second = analyze_engineering_practices(_fullstack_inspection())
    assert first == second


# ---------------------------------------------------------------------------
# Provider integration: additive channel, signals untouched
# ---------------------------------------------------------------------------

def test_build_result_attaches_practices_without_touching_signals():
    res = _direct("dev", "svc", _fullstack_inspection())
    practices = res.raw_metadata.get("engineering_practices")
    assert practices is not None
    assert practices["version"] == MODEL_VERSION
    assert list(practices["dimensions"].keys()) == list(DIMENSIONS)
    assert practices["dimensions"]["testing"]["present"] is True
    assert practices["dimensions"]["containerization"]["score"] == 1.0
    assert practices["summary"]
    for sig in res.signals:
        # The separate dimension must never leak into skill signals.
        assert "engineering_practices" not in sig.metadata
        assert sig.signal_strength == EvidenceDepth.get_strength_for_depth(sig.depth)


def test_compact_inspection_preserves_practices():
    res = _direct("dev", "svc", _fullstack_inspection())
    compact = compact_inspection(res.raw_metadata)
    assert compact.get("engineering_practices", {}).get("version") == MODEL_VERSION
    assert "readme_text" not in compact
    assert "config_text" not in compact


def test_profile_aggregate_unions_practices():
    owner = "practices_dev"
    testing_only = _fullstack_inspection(
        name="tests-only",
        root_files=["requirements.txt", "README.md"],
        top_files=["src/app.py", "tests/test_app.py"],
        python_deps=["pytest"],
        package_json_deps=[],
        usage_patterns={},
        usage_files={},
        config_text="",
        config_files_sampled=[],
        readme_text="readme",
        error_indicators={},
        error_files={},
        ext_file_counts={".py": 2},
        has_workflows=False,
    )
    docker_only = _fullstack_inspection(
        name="docker-only",
        root_files=["Dockerfile", "docker-compose.yml"],
        top_files=["Dockerfile", "docker-compose.yml", "src/app.py"],
        python_deps=[],
        package_json_deps=[],
        usage_patterns={},
        usage_files={},
        config_text="FROM python:3.11\n",
        config_files_sampled=["Dockerfile"],
        readme_text="",
        error_indicators={},
        error_files={},
        ext_file_counts={".py": 1},
        has_workflows=False,
    )
    res = _run(GitHubProvider().verify({
        "source_url": f"https://github.com/{owner}",
        "mock_profile_repos": [
            _inspection_repo(owner, "tests-only", testing_only),
            _inspection_repo(owner, "docker-only", docker_only),
        ],
    }))
    assert res.status == "verified"
    agg = res.raw_metadata.get("engineering_practices")
    assert agg is not None
    assert agg["repositories_analyzed"] == 2
    assert agg["dimensions"]["testing"]["present"] is True
    assert agg["dimensions"]["testing"]["repositories"] == [f"{owner}/tests-only"]
    assert agg["dimensions"]["containerization"]["present"] is True
    assert agg["dimensions"]["containerization"]["repositories"] == [f"{owner}/docker-only"]
    assert agg["summary"]


def test_scoring_formulas_untouched_by_practices():
    # Pipeline version is unchanged: stored verified_signals stay valid.
    from app.services.evidence.base import EVIDENCE_PIPELINE_VERSION
    assert EVIDENCE_PIPELINE_VERSION == 6
    res = _direct("dev", "svc", _fullstack_inspection())
    for sig in res.signals:
        assert sig.signal_strength == EvidenceDepth.get_strength_for_depth(sig.depth)
    prof, _, _, _ = skill_engine.proficiency([s.to_dict() for s in res.signals
                                              if s.skill == "Python"])
    assert prof == EvidenceDepth.get_strength_for_depth(
        next(s.depth for s in res.signals if s.skill == "Python"))


def test_analysis_pipeline_still_runs_with_practices_present():
    from app.services import analysis_run_service as ars
    res = _direct("dev", "svc", _fullstack_inspection())
    evidence = [{
        "id": "ev1",
        "evidence_type": "github",
        "source_url": "https://github.com/dev/svc",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in res.signals],
            "inspection": res.raw_metadata,
        },
    }]
    signals = ars.extract_skill_signals(evidence, [], [])
    assert signals
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map(
        [{"skill": "Python", "required_level": 0.7, "importance": 0.8}], None)
    assessments = ars.calculate_assessments(grouped, req_map, None)
    assert assessments[0]["proficiency"] > 0
