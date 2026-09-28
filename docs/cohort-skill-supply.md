# Cohort Skill Supply (P0 #3)

## 1. Why cohort skill supply exists

P0 #1 (labour-market demand) says which skills industry needs. P0 #2
(institution/course supply) says what institutions teach. Neither says what
learners can *actually do*. This phase closes that gap by aggregating
existing verified learner evidence over course cohorts — answering "what
skills are demonstrated by learners in this course/cohort?" without inventing
new measurements. The output is the supply-side input for P0 #4 alignment:

```
Labour Market Demand
         │
         ↓
   Required Skills
         │
         │
         ↓
    P0 #4 Alignment
         ↑
         │
  Cohort Skill Supply     <-- this phase (P0 #3)
         ↑
         │
 Existing Student Evidence
         ↑
         │
      Students
         ↑
         │
       Cohort
         ↑
         │
       Course
         ↑
         │
    Institution
```

## 2. Institution → Course → Cohort → Student

- **cohorts**: one batch under exactly one institution + one course
  (e.g. "Full Stack Web Development — Batch 2026-A"). Statuses
  draft/active/completed/archived; date sanity enforced.
- **cohort_members**: roster rows keyed by `user_id` — the canonical student
  identifier (`auth.users.id` = `profiles.user_id` =
  `skill_signals.user_id` = `skill_assessments.user_id`). No second student
  or profile table. Leaving a cohort withdraws (soft); history rows are
  retained, and only one *active* membership per (cohort, student) may exist
  (partial unique index + service guard).

## 3. Existing student evidence as source of truth

Per-member skill state is read live from `skill_signals` (source_type,
signal_value, source_reliability per user/skill) and `skill_assessments`
(proficiency, confidence, evidence_weight, source_diversity, evidence_count).
No persisted skill projection exists, so there is nothing to refresh or
invalidate — reads are always current. Per-member proficiency/confidence reuse
`skill_engine.proficiency_with_prior` and `confidence_from_signals` (the exact
student-pipeline functions); tiers reuse `evidence_weights` (`tier_of`,
`has_direct_validation`).

## 4. Definition of evidenced skill

A member counts as **evidenced** for a skill with ≥1 signal from a tier
INAURA treats as evidence — supporting, medium, high, or very_high — or with
an existing `skill_assessments` row. Signals from the low tier
(resume/linkedin/self_declared) alone never qualify, so self-reported-only
members appear in denominators but never as supply.

## 5. Definition of verified skill

A member counts as **verified** with ≥1 assessment-source signal for the
skill (`has_direct_validation`) — the same "validated by assessment" contract
as `analysis_run_service.evidence_state`. Hierarchy: assessed ⊇ evidenced ⊇
verified.

## 6. Skill coverage formula

```
skill_coverage     = evidenced_member_count / active cohort members
verified_coverage  = verified_member_count  / active cohort members
verification_rate  = verified_member_count  / evidenced_member_count
```
It is SUPPLY, never demand. Members with no evidence count only in the
denominator (documented, tested).

## 7. Proficiency aggregation

Over evidenced members only: average, median, min, max of the reused engine
proficiencies — descriptives of the existing 0..1 values, no new bands or
cutoffs. Also exposed: average confidence, qualifying signal count, and
`average_evidence_count` (mean of assessment-row evidence_count where rows
exist, else null).

## 8. Evidence/confidence handling

Every skill row carries `source_distribution` (members per actual source key:
github, assessment, leetcode, … — no invented categories) and
`tier_distribution` (very_high/high/medium/supporting/low), so a cohort of
50 self-reports is visibly different from 50 assessed learners. Confidence is
the reused engine value, averaged over evidenced members.

## 9. Privacy considerations

Per-skill detail requires ≥5 active members
(`MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL`, mirroring the existing skill-level
min-n convention in outcome analytics). Smaller cohorts return counts only
(`suppressed: true`); empty cohorts return zeros without suppression.
Aggregate responses never contain user_ids or per-member evidence (tested by
scanning serialized output). The members roster endpoint returns membership
rows only — no skill evidence. RLS: authenticated SELECT, service-role writes
only, no cross-table policy subqueries (non-recursive by construction,
statically regression-tested).

## 10. API endpoints

`/api/v1/cohorts` CRUD; `/cohorts/{id}/members` add/list;
`PATCH /cohorts/{id}/members/{memberId}` lifecycle;
`DELETE …/members/{memberId}` withdraws softly;
`GET /cohorts/{id}/skill-supply` (cohort + course + institution context,
counts, skills, unmapped concepts, provenance);
`GET /courses/{course_id}/cohorts` and `GET /courses/{course_id}/cohort-supply`
(combined, members deduped). All routes require the existing auth dependency.

## 11. RLS/security model

Migration 032, same reference-data convention as 029/030/031: authenticated
reads, backend service-role writes, anon/PUBLIC revoked. Rationale:
institutional cohort data is not public student data, and per-member evidence
never leaves the aggregate boundary.

## 12. Demo data provenance

`build_demo_seed()` (pure, deterministic) + `seed_demo_data()` (idempotent):
one cohort (`DEMO-FSWD-2026A`) under the P0#2 demo course, six synthetic
members (uuid5 ids — impossible to collide with real users), 16 signals
across real tiers with `metadata.demo_seeded`, all `data_origin='demo_seeded'`.
No assessment rows are fabricated; no real student data touched. Requires the
P0#2 demo to exist first (404 otherwise).

## 13. What is intentionally deferred

Industry↔course/cohort scoring and ranking, recommendations of any kind,
curriculum rewriting, district analysis, trainer/capacity logic, new
assessment or skill engines, new taxonomies. P0 #4 consumes the supply rows
defined here alongside P0 #1 demand and P0 #2 curriculum.
