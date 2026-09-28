# Training Priority Engine (P1.1)

## 1. Purpose

The first action layer over the completed P0 evidence system. It answers
only "how urgent / actionable is this already-observed gap?" — transforming
P0 #5 district rows into HIGH / MEDIUM / LOW / INSUFFICIENT_EVIDENCE
priorities with traceable reasons and compact evidence packets:

> "Training priority is an evidence-based planning signal,
>  not an automatic policy decision."

## 2. Inputs

Everything comes from `district_training_service.get_district_training`
(market blocks, curriculum counts, learner aggregates, trainer signals, gap
states, P0 #5 priority outcomes, market context, suppression flags). No P0
table is read directly and no P0 value is recomputed — except the priority
mapping itself, which is this layer's sole job.

## 3. Priority levels

HIGH, MEDIUM, LOW, INSUFFICIENT_EVIDENCE — the controlled vocabulary (no
CRITICAL/URGENT variants exist in the repo). Mapping from district rows:

- market absent → INSUFFICIENT_EVIDENCE (missing evidence is never LOW);
- attainment undecidable without a supply-independent curriculum gap →
  INSUFFICIENT_EVIDENCE (never HIGH from hidden data);
- otherwise the district high/medium/low outcome, uppercased unchanged.

A separate `status` stays orthogonal to urgency: `aligned`
(fully covered + strong attainment — never mislabelled LOW),
`actionable_gap`, `insufficient_evidence`.

## 4–6. High / medium / low rules

Inherited verbatim from the P0 #4 policy (threshold constants imported, not
copied): HIGH for curriculum-gap ∧ (rising ∨ share ≥ 0.40) or attainment-gap
∧ rising ∧ share ≥ 0.25 on unsuppressed rows; MEDIUM for remaining gaps and
declining signals; LOW otherwise. LOW means "lower current action priority
based on available evidence", never "unimportant skill". Verified identical
to P0 #4 outcomes on shared skills (regression-tested; the single designed
divergence is unmapped-market skills, which P1.1 refuses to call LOW).

## 7. Insufficient-evidence rules

No market evidence, undecidable attainment, suppressed cohorts, unknown
districts, or unmapped roles all yield INSUFFICIENT_EVIDENCE (or empty
results with explanatory notes) — never converted up to HIGH or down to LOW.

## 8. Priority reasons

Restated from district evidence, each traceable to a field: trend/share
phrasing ↔ `market.trend`/`market.skill_share` (values interpolated, e.g.
"share 0.58"); verified-coverage phrasing ↔ learner counts; absence phrasing
↔ `courses_teaching == 0`. No vague claims, no LLM generation.

## 9. Market-context handling

District/role/country/state/city/match-type/period/provider pass through
from the district response; global fallback stays labelled. Incompatible
role contexts are never merged — role is required and normalized, unmapped
roles return an explanatory envelope.

## 10. Privacy

Suppressed districts produce no priorities; per-skill packets contain
aggregates only (responses are serialization-scanned for user ids in tests).

## 11. Capacity limitations

Counts and `capacity_status` pass through; the seat-data note is mandatory
("Capacity recommendation unavailable: no validated capacity data."); no
seat/trainer/centre numbers are ever recommended (regex-tested).

## 12. API

`GET /api/v1/industry/training-priorities` (district, role, location/date/
provider filters, optional priority filter; existing auth) ordered by level,
then observed share (nulls last), then skill slug — documented, deterministic,
and explicitly not a ranking score. `GET /.../training-priorities/{skill}`
returns one packet (404 when absent) for review/detail use and future P1.2.

## 13. Provenance

Engine version, timestamp, district-training version, and the reused P0 #4
threshold values on every response.

## 14. Determinism

Pure mapping + documented sort; full-output equality tested (modulo the
`computed_at` timestamp). No LLM calls anywhere.

## 15. What is intentionally deferred

P1.2 curriculum change proposals (add/increase/update/assess/review actions
as human-reviewable proposals — never automatic rewrites); everything P1.1
was forbidden from building (scores, policies-as-decisions, seat plans).
