"""
Centralized evidence weighting configuration — single source of truth.

Two orthogonal axes are configured here. They must never be conflated:

  source_reliability : how much INAURA trusts the *source* of a claim.
                       Used only as the weighting factor in the proficiency
                       weighted average. It is NOT a proficiency value.

  source_directness  : how directly the source demonstrates the *person's own
                       current ability*. Used only by the confidence model, to
                       express that an inspected repository shows exposure
                       while a graded assessment shows demonstrated ability.

Reliability hierarchy (prototype heuristic, not validated psychometrics):

  VERY HIGH  assessment                             0.95
  HIGH       leetcode / codeforces / kaggle         0.85
             syllabus / coursework                  0.80
  MEDIUM     project                                0.62
             github                                 0.60
             certification / certification_file     0.55
             project_doc                            0.55
  LOW        resume                                 0.50
             linkedin                               0.40
             self_declared                          0.30

Calibration note (2026-09 recalibration):
  * `github` moved 0.70 -> 0.60 and `project` moved 0.90 -> 0.62. Repository
    and self-described project evidence proves technology *exposure*; with
    AI-assisted development it does not reliably prove personal proficiency,
    so it must sit in the MEDIUM band below performance-based platforms and
    verified coursework. Previously `project` (0.90) outranked every other
    source, which let self-declared project entries dominate proficiency.
  * `project_doc` moved 0.75 -> 0.55: documentation about a project is weaker
    than the project artifacts themselves.
  * `assessment` (0.95) is new: a graded INAURA skill assessment is the only
    source that directly probes the person rather than an artifact.
  * All other values are unchanged from the previous calibration.
"""

from typing import Dict, Iterable, List, Optional

# Canonical source key for INAURA's own graded skill assessment.
ASSESSMENT_SOURCE = "assessment"

# Weighting factor applied to each evidence signal in the proficiency average.
SOURCE_RELIABILITY: Dict[str, float] = {
    # VERY HIGH — direct validation of the person
    "assessment": 0.95,
    # HIGH — performance-based platforms and verified coursework
    "leetcode": 0.85,
    "codeforces": 0.85,
    "kaggle": 0.85,
    "syllabus": 0.80,
    "coursework": 0.80,
    # MEDIUM — artifact evidence and credentials
    "project": 0.62,
    "github": 0.60,
    "certification": 0.55,
    "certification_file": 0.55,
    "project_doc": 0.55,
    # LOW — self-reported
    "resume": 0.50,
    "linkedin": 0.40,
    "self_declared": 0.30,
}

DEFAULT_RELIABILITY = 0.50

# Named tiers, used for reporting and for tier-level assertions.
RELIABILITY_TIERS: Dict[str, List[str]] = {
    "very_high": ["assessment"],
    "high": ["leetcode", "codeforces", "kaggle", "syllabus", "coursework"],
    "medium": ["project", "github", "certification", "certification_file", "project_doc"],
    "low": ["resume", "linkedin", "self_declared"],
}

TIER_ORDER: List[str] = ["low", "medium", "high", "very_high"]

# How directly a source demonstrates the person's own current ability.
# Confidence-model input only — never used as a proficiency or a weight.
SOURCE_DIRECTNESS: Dict[str, float] = {
    # Graded, person-facing assessment: fully direct
    "assessment": 1.00,
    # Performance platforms: the person solved the problems themselves
    "leetcode": 0.80,
    "codeforces": 0.80,
    "kaggle": 0.75,
    # Verified coursework: institution-observed but not INAURA-observed
    "syllabus": 0.60,
    "coursework": 0.60,
    # Artifacts: show that work exists, not who understood it
    "project": 0.45,
    "github": 0.40,
    "project_doc": 0.35,
    "certification": 0.35,
    # Self-reported
    "resume": 0.15,
    "linkedin": 0.10,
    "self_declared": 0.05,
}

DEFAULT_DIRECTNESS = 0.20


def _source_of(signal: dict) -> str:
    return str(signal.get("source") or signal.get("source_type") or "").strip().lower()


def reliability(source_type: str) -> float:
    """Reliability weight for a source key (falls back to DEFAULT_RELIABILITY)."""
    return SOURCE_RELIABILITY.get(str(source_type or "").strip().lower(), DEFAULT_RELIABILITY)


def directness(source_type: str) -> float:
    """Directness factor for a source key (falls back to DEFAULT_DIRECTNESS)."""
    return SOURCE_DIRECTNESS.get(str(source_type or "").strip().lower(), DEFAULT_DIRECTNESS)


def tier_of(source_type: str) -> str:
    """Return the named reliability tier for a source key."""
    key = str(source_type or "").strip().lower()
    for tier, members in RELIABILITY_TIERS.items():
        if key in members:
            return tier
    return "low"


def validation_strength(signals: Iterable[dict]) -> float:
    """
    Strongest *direct* demonstration among a skill's signals, in [0, 1].

    For each signal: directness(source) x signal_strength. A graded assessment
    scoring 0.8 yields 0.80; a strong GitHub implementation signal (0.75) yields
    0.30. Taking the maximum (rather than a sum) keeps piles of weak artifact
    evidence from imitating one piece of direct evidence.
    """
    best = 0.0
    for s in signals or []:
        raw = s.get("signal_strength", s.get("signal_value", 0.0))
        try:
            strength = float(raw)
        except (TypeError, ValueError):
            strength = 0.0
        strength = max(0.0, min(1.0, strength))
        best = max(best, directness(_source_of(s)) * strength)
    return max(0.0, min(1.0, best))


def has_direct_validation(signals: Iterable[dict]) -> bool:
    """True when at least one signal comes from INAURA's own assessment."""
    return any(_source_of(s) == ASSESSMENT_SOURCE for s in (signals or []))


def describe() -> Dict[str, object]:
    """Machine-readable snapshot of the weighting model (for reports/debug)."""
    return {
        "reliability": dict(SOURCE_RELIABILITY),
        "directness": dict(SOURCE_DIRECTNESS),
        "tiers": {k: list(v) for k, v in RELIABILITY_TIERS.items()},
        "default_reliability": DEFAULT_RELIABILITY,
        "prototype_disclaimer": (
            "Heuristic prototype weights for career guidance. Not validated "
            "psychometric measurement of human proficiency."
        ),
    }
