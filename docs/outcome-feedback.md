# Outcome Feedback (P1.6)

## 1. Purpose

Observational read-only feedback: what happened after training signals, in
observed employer feedback, skill ratings, qualification alignments, and
placement outcomes. It evaluates whether intelligence looks aligned with
reality; it never rewrites assessments, gaps, or priorities.

## 2. Sources (existing tables only)

`applications`, `employer_feedback`, `employer_skill_feedback`
(expected/observed levels per skill), `qualification_alignments` (coverage),
`placement_outcomes` (status, role, dates, verification). No new tables, no
migration.

## 3. Joins (canonical IDs only)

Skill via `skill_id`; role via requirement `role_key` or placement
`role_title` through role normalization; course/district/institution via
student ever-membership in cohorts (documented approximation — outcomes are
not timestamp-matched to active enrollment); proposals resolve through P1.2
to course + skill. No name-based inference anywhere.

## 4. Signal states

Per skill, gated on ≥ 5 feedback observations (reused outcome skill-level
convention): `SUPPORTIVE_SIGNAL` (mean observed−expected ≥ 0), `MIXED_SIGNAL`
(slightly below, within the named 0.10 presentation band),
`CONTRADICTORY_SIGNAL` (clearly below), else `INSUFFICIENT_OUTCOME_EVIDENCE`.
Counts below 5 are nulled with suppression flags. Placement volume is
reported alongside but never flips a signal without a feedback baseline.

## 5. No causal claims

Every signal carries its limitation in plain language ("describes past
observations, not a causal effect"); provenance repeats the contract.
Mismatch flags (HIGH/MEDIUM priority + contradictory feedback) describe
co-occurrence only. Tested by scanning all output for causal phrasing.

## 6. Privacy

Aggregates only (serialization-tested with identifying fixtures, including
private comments and outsider records, which are excluded from district
scope). Small cells suppressed. RLS unchanged: reads flow through the
authenticated API over the service-role client, like other analytics.

## 7. API

`GET /api/v1/industry/outcome-feedback` (district/role/course/institution/
skill/proposal/date filters; existing auth) and
`GET /.../outcome-feedback/{skill}` (404 when unobserved). Time periods
echoed; undated rows join only unfiltered windows per documented rules.

## 8. Limitations

Ever-membership approximation; requirement-side alignments unattributable
under course filters; no placement skill linkage (placements lack a skill
column); feedback depth, not placement volume, signs each signal.

## 9. What is NOT built

Causal inference, score changes, assessment writes, new outcome tables,
employer-facing write paths, or any automatic refresh of earlier layers.
Feedback is exposed for future reassessment, never applied by this layer.
