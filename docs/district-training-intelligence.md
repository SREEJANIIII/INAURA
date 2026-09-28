# District Training Intelligence (P0 #5)

## 1. Purpose

Evidence-backed district planning inputs aggregating the four completed
layers — measurements, gaps, priorities, and signals, never unsupported
prescriptions:

```
              DISTRICT
                 │
     ┌───────────┼────────────┐
     ↓           ↓            ↓
Institutions  Courses      Cohorts  (P0 #2, P0 #3 rosters)
     │           │            │
     ↓           ↓            ↓
 Trainers    Curriculum    Learners (P0 #2 skills, P0 #3 evidence)
     │           │            │
     └───────────┼────────────┘
                 ↓
           SKILL SUPPLY (learner-weighted)
                 │
                 + LABOUR DEMAND (P0 #1 via P0 #4)
                 ↓
           P0 #4 ALIGNMENT (per course)
                 ↓
     DISTRICT INTELLIGENCE (this phase)
```

## 2. District definition

A district is the literal `institution.district` string (+ state/country
context). Districts are never inferred from names, never geocoded, and
city ≠ district / region ≠ district unless the data says so. A query with
no matching institutions returns `district_status: "unknown"` with zeros —
nothing fabricated.

## 3. Market context

Demand reaches the district only through per-course P0 #4 alignments run
with the district's role/location/date/provider filters, reusing P0 #1
location semantics verbatim. `match_type` is therefore `exact`,
`fallback_global` (global rows apply everywhere but are labelled, never
presented as district-measured demand), or `insufficient_data`. There is no
regional fallback because P0 #1 has no regional matching — documented, not
invented. A district with no active courses reports insufficient market
context rather than borrowing demand without a course anchor.

## 4–6. Institution / course / cohort aggregation

Institutions (with by-type counts), active courses (with by-delivery-mode
counts), all cohorts of those courses, and active learner totals come from
direct P0 #2/P0 #3 reads. Only active courses scope the district; cohort
status does not filter learners (active membership does).

## 7. Skill supply aggregation

Per-cohort P0 #3 skill rows aggregated with learner weighting:
district coverage = Σ evidenced / Σ learners (never averaged percentages;
medians are not composable, so only min/max-style descriptives plus weighted
means are exposed). Only unsuppressed cohorts contribute per-skill detail;
suppressed cohorts contribute counts. A district with no unsuppressed
learners suppresses all skill detail. Cross-cohort roster overlap would
double-count — documented limitation (privacy forbids the member-level
dedupe that would fix it).

## 8. Learner-weighted calculations

See §7. Tested with the specification's case (8/10 + 20/100 = 28/110 ≈
0.2545, not 0.50) and against independently recomputed weighted means from
P0 #3 cohort rows.

## 9–10. Curriculum and attainment gaps

Per skill: `district_curriculum_gap` (in demand, taught in 0 district
courses), `partially_covered` / `fully_covered`, `no_market_demand`
(taught without demand rows — no evidence ≠ no demand). Attainment reuses
the P0 #4 verified-coverage bands on district coverage
(`district_attainment_gap` below 0.20); unavailable supply →
`insufficient_evidence`; untaught/undemanded skills → `not_applicable`.
Concentration is descriptive only: absent / concentrated (one institution of
many) / distributed / not_applicable — never an automatic failure, never
alone sufficient for high priority.

## 11. Trainer signals

P0 #2 trainer skills aggregated per skill: trainer_count,
institutions_with_skill_trainers, coverage share, and signal
observed / no_trainer_observed / not_applicable. No trainer-to-student
ratios are invented, so `capacity_status` stays `insufficient_data`.

## 12. Capacity evidence

Exposes course/cohort/learner/trainer counts plus gap presence and a
mandatory honesty note — INAURA does not infer exact seat allocations
without validated course-capacity data. `capacity_evidence_status` is
`partial_data` for populated districts, `insufficient_data` for empty ones,
never `sufficient_data` (no seat data exists in the repository).

## 13. Priority signals

Same rule shape as the P0 #4 policy with its imported named constants:
high for (curriculum gap ∧ (rising ∨ share ≥ 0.40)) or (attainment gap ∧
rising ∧ share ≥ 0.25) on unsuppressed rows; medium for gaps and declining
signals; low otherwise — always with structured evidence reasons
(district verified coverage across N learners, courses-teaching counts,
trend/share). Verified consistent with P0 #4 on single-course districts.

## 14. Privacy

P0 #3 suppression propagates; outputs are aggregates only (serialized
responses are scanned for user ids in tests); no repositories, interviews,
or assessment responses cross the boundary.

## 15. Provenance

Engine version, timestamp, P0 #4/P0 #3 versions, demand source chain,
district query, and suppression counts on every response.

## 16. API

`GET /api/v1/industry/district-training`
(district, role, state/country/region/city, dates, provider; existing auth).
Single comprehensive endpoint returning context, institutions, skills,
summary, capacity, unmapped counts, and provenance. No persistence: live
projection, no migration.

## 17. Limitations

No district-granular demand exists (city/country/global only); no seat data;
cross-cohort overlap double-counts; course-less districts get no market
block; district medians don't exist (see §7).

## 18. What is intentionally deferred

P1 planning actions: seat allocations, curriculum rewrites, trainer
development plans, course redesign, employer-feedback loops,
placement/outcome validation, AI-generated recommendations.
