# Course / Industry Alignment (P0 #4)

## 1. Purpose

Deterministic, explainable answers to "does this training align with
industry demand?" by joining the three completed foundations — no LLM
judgments, no opaque score:

```
INDUSTRY DEMAND
      ↓
REQUIRED SKILLS
      ↓
┌─────────────────────────────┐
│ COURSE / INDUSTRY ALIGNMENT │
└─────────────────────────────┘
      ↑              ↑
      │              │
COURSE SKILLS    COHORT SUPPLY
      ↑              ↑
      │              │
    P0 #2          P0 #3
```

## 2. Inputs from P0 #1

`labour_market_service.get_demand_signals` (canonical rows only) filtered by
role/date/provider, then P0 #1 location semantics applied verbatim
(`industry_intelligence.location_matches`): global-scope rows apply
everywhere; scoped rows apply on exact key match only. City demand is never
fabricated — a global query over city-only rows yields no demand, and a
partial location (city without country/region) cross-matches nothing. Demand
is never recalculated; per skill the latest period row wins (ties: largest
sample, then provider id). Suppressed tiny-sample rows are kept but flagged
and can never drive high priority.

## 3. Inputs from P0 #2

`institution_service.get_course_coverage` flattened to
slug → {coverage, importance, modules, mapping_status, source_concept}.
Unmapped curriculum concepts are counted and excluded. Firm teaching =
intermediate/advanced coverage.

## 4. Inputs from P0 #3

`cohort_supply_service.get_cohort_skill_supply` (single cohort, validated to
belong to the course) or `get_course_cohort_supply` (combined, members
deduped). Suppression and privacy rules ride along unchanged: suppressed or
empty supply forces `insufficient_evidence` attainment. Responses never
contain student-level data.

## 5. Canonical skill joining

Join key is the canonical slug everywhere (demand `skill_slug`, course
`canonical_skill_slug`, supply `skill`). Display names resolve via the
taxonomy with source-concept fallback. Unmapped concepts from any source are
counted in `unmapped_excluded` and excluded from rows — never fabricated
into mappings. Skill universe = demand slugs ∪ taught slugs; demonstrated-
but-neither skills surface as `extra_cohort_skills` (slugs only).

## 6. Curriculum gap definition

In the demand set but absent from the course → `curriculum_status =
"missing"`, `overall_status = "curriculum_gap"`. Taught skills are `covered`
(intermediate/advanced) or `weakly_covered` (introductory/unstated). This is
distinct from learner attainment.

## 7. Attainment gap definition

Taught skill with weak verified learner supply → `attainment_status =
"weak"`, `overall_status = "attainment_gap"`; moderate supply →
`weak_supply`; strong → `aligned`. Bands over cohort `verified_coverage`
(named policy: strong ≥ 0.50, moderate ≥ 0.20 — documented in the service
because the architecture has no pre-existing cohort bands). Unavailable
supply → `insufficient_evidence` → `insufficient_data`.

## 8. Demand status definition

Pass-through of the P0 #1 trend: rising / stable / declining / emerging /
insufficient_data; `insufficient_market_evidence` when the course teaches a
skill with no demand row (no evidence ≠ no demand — never "useless"). Low
share (< 0.15) and declining signals are descriptive flags ("descriptive
only"); nothing is ever labelled obsolete.

## 9. Market-context handling

`market_context` records role, requested country/region/city/scope,
`location_match` (exact vs fallback_global), observed period range,
providers, and data origins. The alignment unit is therefore always
role + course + skill + market context — incompatible contexts are never
silently mixed.

## 10. Insufficient-data handling

Missing demand, missing cohort detail, suppressed samples, and unmapped
roles all produce explicit `insufficient_data`/`insufficient_evidence`
statuses with reasons — never silent zeros, never strong conclusions.

## 11. Privacy handling

P0 #3 suppression respected end to end; no user ids, repositories,
interviews, or assessment responses cross the boundary (serialization-tested).

## 12. Provenance

Every response carries engine version, timestamp, demand providers/origins,
course origin, cohort-supply source, per-row evidence contexts, and the
"live projection, no persisted records, no LLM" note. Priority reasons cite
the evidence (trend + share, absence from curriculum, weak verified supply).

## 13. API

`GET /api/v1/industry/course-alignment` (course_id, role, optional
cohort_id/country/region/city/start_date/end_date/provider_id; existing
auth). Returns market context, course/institution info, skill rows
(industry/curriculum/cohort/alignment blocks), summary counts (no course
score), extra cohort skills, unmapped counts, provenance. No persistence:
reads are live projections, so no refresh/invalidation/versioning beyond the
engine version.

## 14. Deterministic rules

Status precedence: no demand → insufficient_data; missing curriculum →
curriculum_gap; weak attainment → attainment_gap; moderate → weak_supply;
strong → aligned. Priority high only for (missing ∧ (rising ∨ share ≥ 0.40))
or (weak ∧ rising ∧ share ≥ 0.25) on unsuppressed rows; medium for gaps and
declining signals; low otherwise. Required/course/cohort levels are
preserved side by side, never collapsed (postings don't observe
required_level — null stays null).

## 15. What is intentionally NOT implemented

District planning (P0 #5), trainer/capacity recommendations, curriculum
rewriting, AI-generated explanations, an "outdated" verdict, aggregate
course scores, frontend dashboards beyond the small additive Course
Alignment block on the Industry Intelligence page.
