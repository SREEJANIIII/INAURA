"""
Regression tests for provenance inconsistency fix.

Covers required cases:
1. README-only L1
2. dependency-only L2
3. single implementation file L3
4. substantial multi-file L4
5. rejected implementation candidate must not leave misleading metadata
6. multiple repositories distinct provenance
7. forked repository depth cap
8. cached stale pipeline reverified
9. never produce depth 1 with substantial usage
10. frontend coherence (via python equivalent of evidenceCard logic)
"""

import asyncio
from datetime import datetime, timezone
import pytest

from app.services.evidence.base import EvidenceDepth, EVIDENCE_PIPELINE_VERSION
from app.services.evidence.github import GitHubProvider
from app.services import analysis_run_service as ars
from app.services import signal_extractor as se
from app.services.evidence.manager import evidence_manager
from app.services.evidence.base import VerificationStatus


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
    return GitHubProvider()._build_result_from_inspection(owner, repo, inspection, datetime.now(timezone.utc))

def _verify(owner, repos):
    return asyncio.run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}))

# 1. README-only skill: depth L1, usage mentioned, no impl files
def test_readme_only_depth_l1():
    res = _direct("dev", "site", {
        "name": "site",
        "readme_text": "Built with React",
        "languages": {},
        "root_files": ["README.md"],
        "top_files": [],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "React" in by_skill
    sig = by_skill["React"]
    assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
    assert sig.metadata.get("usage_status") == "mentioned"
    # relevant files should be doc only, not impl
    rel = sig.metadata.get("relevant_files", [])
    assert all("readme" in f.lower() or f.lower().endswith(".md") for f in rel)
    assert not sig.metadata.get("detected_usage_patterns")
    assert sig.metadata.get("file_importance") == "low"

# 2. dependency-only skill: depth L2, usage declared
def test_dependency_only_depth_l2():
    res = _direct("dev", "web", {
        "name": "web",
        "languages": {},
        "root_files": ["package.json"],
        "top_files": [],
        "package_json_deps": ["react"],
        "tree_scanned": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_2_CONFIG
    assert sig.metadata.get("usage_status") == "declared"
    # L2 must not claim impl patterns or substantial
    assert sig.metadata.get("usage_status") != "substantial"
    assert sig.metadata.get("file_importance") in ("medium", "low")

# 3. single implementation file: depth L3, usage used/imported
def test_single_impl_depth_l3():
    res = _direct("dev", "app", {
        "name": "app",
        "languages": {"TypeScript": 15000},
        "root_files": ["package.json"],
        "top_files": ["src/App.jsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 1},
        "source_files_sampled": ["src/App.jsx"],
        "tree_scanned": True,
        "ext_file_counts": {".jsx": 1},
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert sig.metadata.get("usage_status") in ("imported", "used")
    assert sig.metadata.get("file_importance") in ("high", "very_high")
    assert len(sig.metadata.get("relevant_files", [])) >= 1

# 4. substantial multi-file implementation: depth L4, usage substantial
def test_substantial_multi_file_l4():
    res = _direct("dev", "dashboard", {
        "name": "dashboard",
        "languages": {"TypeScript": 60000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx", "tests/app.test.tsx"],
        "package_json_deps": ["react", "react-dom", "react-router-dom", "typescript", "jest", "tailwindcss"],
        "import_tokens": {"react": 5, "react-router-dom": 2},
        "source_files_sampled": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"],
        "usage_patterns": {"React": {"hook_useState": 2, "hook_useEffect": 2, "jsx_component": 3, "router": 1}},
        "usage_files": {"React": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"]},
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 6, ".ts": 2},
        "has_workflows": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert sig.metadata.get("usage_status") == "substantial"
    assert len(sig.metadata.get("relevant_files", [])) >= 2
    assert len(sig.metadata.get("detected_usage_patterns", [])) >= 2
    assert sig.metadata.get("file_importance") in ("high", "very_high")

# 5. rejected implementation candidate must not retain misleading metadata
def test_rejected_impl_not_leak():
    # This repo has impl-like evidence but files are low importance (docs) so depth capped to L1
    # After fix, L1 signal must not retain impl files or substantial usage
    res = _direct("dev", "low-impl", {
        "name": "low-impl",
        "languages": {"Python": 40000},
        "root_files": ["README.md"],
        "top_files": ["docs/guide.md"],
        "python_deps": ["fastapi"],
        "import_tokens": {"fastapi": 3},
        "source_files_sampled": ["docs/guide.md"],
        "usage_patterns": {"REST APIs": {"fastapi_app": 2}},
        "usage_files": {"REST APIs": ["docs/guide.md"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 0},
        "has_workflows": True,
    })
    # Find REST APIs signal – should be capped to L1 due to low file importance
    by_skill = {s.skill: s for s in res.signals}
    # REST APIs present
    assert "REST APIs" in by_skill
    sig = by_skill["REST APIs"]
    # Should be downgraded to L1 or at least not substantial with impl files
    # After fix, this repo's REST APIs depth is 1 (low importance caps)
    assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
    assert sig.metadata.get("usage_status") == "mentioned"
    assert not sig.metadata.get("detected_usage_patterns")
    # relevant_files should be doc only, not impl
    rel = sig.metadata.get("relevant_files", [])
    assert all("readme" in f.lower() or f.lower().endswith((".md",".txt")) for f in rel)
    # Also test that a doc-only aggregated signal is rejected (no skill)
    owner = "rej_dev"
    repos = [
        _inspection_repo(owner, "notes", {
            "name": "notes",
            "readme_text": "Built with React",
            "languages": {},
            "root_files": ["README.md"],
            "top_files": [],
            "tree_scanned": True,
        })
    ]
    agg = _verify(owner, repos)
    assert "React" not in {s.skill for s in agg.signals}

# 6. multiple repositories: one L1 + one L3/L4 must preserve distinct provenance
def test_multiple_repos_distinct_provenance():
    owner = "multi_dev"
    repos = [
        _inspection_repo(owner, "doc-only", {
            "name": "doc-only",
            "readme_text": "Built with React",
            "languages": {},
            "root_files": ["README.md"],
            "top_files": [],
            "tree_scanned": True,
        }),
        _inspection_repo(owner, "impl", {
            "name": "impl",
            "languages": {"TypeScript": 60000},
            "root_files": ["package.json"],
            "top_files": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
            "package_json_deps": ["react"],
            "import_tokens": {"react": 5},
            "source_files_sampled": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
            "usage_patterns": {"React": {"hook_useState": 3, "jsx_component": 3}},
            "usage_files": {"React": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"]},
            "tree_scanned": True,
            "ext_file_counts": {".tsx": 4},
            "has_workflows": True,
        }),
    ]
    res = _verify(owner, repos)
    by_skill = {s.skill: s for s in res.signals}
    assert "React" in by_skill
    agg = by_skill["React"]
    # Source-level depth should be strongest (L4)
    assert agg.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    # Provenance must preserve both repos separately
    repos_meta = agg.metadata.get("repositories", [])
    assert len(repos_meta) == 2
    depths = {r.get("full_name"): r.get("depth") for r in repos_meta}
    assert depths[f"{owner}/doc-only"] == EvidenceDepth.LEVEL_1_MENTION
    assert depths[f"{owner}/impl"] == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    # Classifications preserved
    classes = {r.get("full_name"): r.get("classification") for r in repos_meta}
    assert classes[f"{owner}/doc-only"] == "owned_active"
    assert classes[f"{owner}/impl"] == "owned_active"
    # Also test that source-level usage is substantial (from impl), not mentioned
    assert agg.metadata.get("usage_status") == "substantial"
    # But per-repo usage must match per-repo depth (doc repo mentioned, impl substantial)
    usage_by_repo = {r.get("full_name"): r.get("usage_status") for r in repos_meta}
    assert usage_by_repo[f"{owner}/doc-only"] == "mentioned"
    assert usage_by_repo[f"{owner}/impl"] == "substantial"

# 7. forked repository: fork evidence must respect depth cap
def test_fork_capped():
    res = _direct("dev", "forked-repo", {
        "name": "forked-repo",
        "languages": {"TypeScript": 60000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 5},
        "source_files_sampled": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
        "usage_patterns": {"React": {"hook_useState": 3, "jsx_component": 3}},
        "usage_files": {"React": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"]},
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 4},
        "has_workflows": True,
        "is_fork": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_2_CONFIG  # capped
    assert sig.depth <= EvidenceDepth.LEVEL_2_CONFIG
    assert sig.metadata.get("usage_status") == "declared"  # not substantial
    assert sig.metadata.get("file_importance") in ("medium", "low")
    assert sig.metadata.get("is_fork") is True
    # Aggregated fork-only profile
    owner = "fork_owner"
    repos = [
        _inspection_repo(owner, "forked-impl", {
            "name": "forked-impl",
            "languages": {"TypeScript": 60000},
            "root_files": ["package.json"],
            "top_files": ["src/App.tsx"],
            "package_json_deps": ["react"],
            "import_tokens": {"react": 5},
            "source_files_sampled": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
            "usage_patterns": {"React": {"hook_useState": 3}},
            "usage_files": {"React": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"]},
            "tree_scanned": True,
            "ext_file_counts": {".tsx": 4},
            "has_workflows": True,
            "is_fork": True,
        }, fork=True)
    ]
    agg = _verify(owner, repos)
    # Fork-only should be capped to L2 even if impl
    # But validation may reject weak? In this case fork with L2 is accepted? Check.
    # For React fork substantial pre-cap, after cap L2, should be accepted as config
    # Our test expects that if only forks, final depth <=2
    for s in agg.signals:
        assert s.depth <= EvidenceDepth.LEVEL_2_CONFIG
        assert s.metadata.get("usage_status") != "substantial"

# 8. cached evidence with older pipeline must be reverified
def test_stale_cached_reverified():
    # evidence_manager should not return cached stale
    old_ev = {
        "id": "ev-old",
        "evidence_type": "github",
        "source_url": "https://github.com/old/repo",
        "verification_status": "verified",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "verification_status": "verified",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "evidence_pipeline_version": EVIDENCE_PIPELINE_VERSION - 1,  # stale
            "verified_signals": [{
                "skill": "Python", "signal_strength": 0.75,
                "depth": 3, "reason": "old",
                "source_reliability": 0.40, "metadata": {"evidence_depth": 3},
            }],
            "provider": "github",
        }
    }
    # manager without force_refresh should treat as stale and not return cached
    # It will attempt to verify via provider (which would need network). For test we check that it does NOT return cached stale directly
    # Instead it should fall through to provider path; we can check that cached provider not returned
    # Since we use mock, it will try to verify and likely fail with invalid URL? But we can test the version check logic directly
    from app.services.analysis_run_service import evidence_refresh_state
    is_unverified, is_stale = evidence_refresh_state(old_ev)
    assert not is_unverified
    assert is_stale is True
    # current version not stale
    cur = dict(old_ev)
    cur["metadata"] = dict(old_ev["metadata"])
    cur["metadata"]["evidence_pipeline_version"] = EVIDENCE_PIPELINE_VERSION
    assert evidence_refresh_state(cur) == (False, False)
    # signal_extractor should skip stale explicit version
    from unittest.mock import patch
    import app.services.skill_taxonomy as taxonomy
    def fake_norm(raw, client=None):
        return raw if raw in ("Python", "React") else None
    with patch.object(se, "get_supabase_client", lambda: type('c', (), {})()):
        with patch.object(se, "normalize_skill", fake_norm):
            with patch.object(taxonomy, "normalize_skill", fake_norm):
                sigs = se.extract_signals([old_ev], [], [])
                # stale explicit version should be skipped (no signals)
                assert len(sigs) == 0
    # legacy without version should still work (backward compat) but not for stale explicit
    legacy = dict(old_ev)
    legacy["metadata"] = {"verification_status": "verified", "verified_signals": old_ev["metadata"]["verified_signals"]}
    legacy["verification_status"] = "verified"
    with patch.object(se, "get_supabase_client", lambda: type('c', (), {})()):
        with patch.object(se, "normalize_skill", fake_norm):
            with patch.object(taxonomy, "normalize_skill", fake_norm):
                sigs2 = se.extract_signals([legacy], [], [])
                # legacy without version still emits (backward compat)
                assert len(sigs2) == 1

# 9. never produce depth 1 with substantial usage
def test_never_mention_with_substantial():
    # Try various combos that previously produced bug: mixed fork+owned, low importance, etc.
    # 1) fork substantial + owned mention aggregated
    owner = "bug_dev"
    repos = [
        _inspection_repo(owner, "owned-mention", {
            "name": "owned-mention",
            "readme_text": "Built with React",
            "languages": {},
            "root_files": ["README.md"],
            "top_files": [],
            "tree_scanned": True,
        }),
        _inspection_repo(owner, "forked-impl", {
            "name": "forked-impl",
            "languages": {"TypeScript": 60000},
            "root_files": ["package.json"],
            "top_files": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
            "package_json_deps": ["react"],
            "import_tokens": {"react": 5},
            "source_files_sampled": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
            "usage_patterns": {"React": {"hook_useState": 3, "jsx_component": 3}},
            "usage_files": {"React": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"]},
            "tree_scanned": True,
            "ext_file_counts": {".tsx": 4},
            "has_workflows": True,
            "is_fork": True,
        }, fork=True)
    ]
    agg = _verify(owner, repos)
    for sig in agg.signals:
        if sig.depth == EvidenceDepth.LEVEL_1_MENTION:
            assert sig.metadata.get("usage_status") != "substantial", f"depth 1 with substantial for {sig.skill}"
            rel = sig.metadata.get("relevant_files", [])
            # relevant_files for L1 must not be impl
            assert not any("src/" in f for f in rel), f"L1 with impl files {rel}"
            assert not sig.metadata.get("detected_usage_patterns")
    # 2) per-repo low importance case
    res = _direct("dev", "low-impl", {
        "name": "low-impl",
        "languages": {"Python": 40000},
        "root_files": ["README.md"],
        "top_files": ["docs/guide.md"],
        "python_deps": ["fastapi"],
        "import_tokens": {"fastapi": 3},
        "source_files_sampled": ["docs/guide.md"],
        "usage_patterns": {"REST APIs": {"fastapi_app": 2}},
        "usage_files": {"REST APIs": ["docs/guide.md"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 0},
        "has_workflows": True,
    })
    for sig in res.signals:
        if sig.depth == EvidenceDepth.LEVEL_1_MENTION:
            assert sig.metadata.get("usage_status") in ("mentioned", "none", None)
            assert sig.metadata.get("usage_status") != "substantial"
    # 3) Check all signals across a realistic profile never violate
    owner2 = "check_all"
    repos2 = [
        _inspection_repo(owner2, "a", {"name": "a", "readme_text": "Python rocks", "languages": {}, "root_files": ["README.md"], "top_files": [], "tree_scanned": True}),
        _inspection_repo(owner2, "b", {"name": "b", "languages": {"Python": 50000}, "root_files": ["requirements.txt"], "top_files": ["src/main.py"], "python_deps": ["pandas"], "import_tokens": {"pandas": 5}, "source_files_sampled": ["src/main.py"], "tree_scanned": True, "ext_file_counts": {".py": 5}}),
    ]
    agg2 = _verify(owner2, repos2)
    for sig in agg2.signals:
        sdepth = sig.metadata.get("usage_status")
        # map to depth
        from app.services.evidence.usage_status import STATUS_TO_DEPTH
        if sdepth:
            sd = STATUS_TO_DEPTH.get(sdepth, 0)
            assert sd <= sig.depth, f"usage {sdepth} depth {sd} > signal depth {sig.depth} for {sig.skill}"

# 10. frontend coherence check: evidenceDepth 1 must not display substantial usage
def test_frontend_coherence():
    # Simulate what evidenceCard.ts githubBullets does: it should not show substantial when depth is 1
    # We test the backend ensures such payload never occurs, so frontend won't have to hide
    # Here we verify that our backend never produces incoherent payload, and frontend helper would correctly filter
    # Import frontend logic via python equivalent: status depth check
    from app.services.evidence.usage_status import STATUS_TO_DEPTH
    # Simulate source details with depth 1 but usage substantial (incoherent) – frontend should filter
    def frontend_would_show_usage(details):
        usage = details.get("usage_status")
        depth = details.get("evidence_depth")
        if not usage:
            return False
        sd = STATUS_TO_DEPTH.get(usage, 0)
        try:
            d = int(depth)
        except:
            return True
        return sd <= d

    # Incoherent payload should not be shown
    assert not frontend_would_show_usage({"evidence_depth": 1, "usage_status": "substantial"})
    assert frontend_would_show_usage({"evidence_depth": 4, "usage_status": "substantial"})
    assert frontend_would_show_usage({"evidence_depth": 2, "usage_status": "declared"})
    assert not frontend_would_show_usage({"evidence_depth": 2, "usage_status": "substantial"})
    # Also check via actual backend never produces incoherent
    res = _direct("dev", "site", {
        "name": "site",
        "readme_text": "Built with React",
        "languages": {},
        "root_files": ["README.md"],
        "top_files": [],
        "tree_scanned": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    details = {"evidence_depth": sig.depth, "usage_status": sig.metadata.get("usage_status")}
    assert frontend_would_show_usage(details)

def test_build_evidence_sources_coherence():
    # Verify that analysis_run_service build_evidence_sources preserves coherence
    owner = "src_dev"
    from app.services.evidence.github import GitHubProvider
    # Create a realistic impl repo
    prov = _verify(owner, [_inspection_repo(owner, "svc", {
        "name": "svc",
        "languages": {"Python": 40000},
        "root_files": ["requirements.txt"],
        "top_files": ["backend/api/users.py"],
        "python_deps": ["fastapi"],
        "import_tokens": {"fastapi": 2},
        "source_files_sampled": ["backend/api/users.py"],
        "usage_patterns": {"REST APIs": {"fastapi_app": 1}},
        "usage_files": {"REST APIs": ["backend/api/users.py"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 2},
        "has_workflows": True,
    })])
    signals = se.extract_signals([{
        "id": "ev1", "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in prov.signals],
            "evidence_pipeline_version": EVIDENCE_PIPELINE_VERSION,
        },
    }], [], [])
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map([{"skill": "Python", "required_level": 0.7, "importance": 0.8}], None)
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    # Find Python assessment
    if "Python" in assessments:
        py = assessments["Python"]
        gh = next((s for s in py["evidence_sources"] if s["source_type"] == "github"), None)
        assert gh is not None
        d = gh["details"]
        # Details should have coherent provenance
        assert d["evidence_depth"] == gh["evidence_depth"]
        if d["evidence_depth"] == 1:
            assert d.get("usage_status") != "substantial"
            assert not d.get("detected_usage_patterns")
