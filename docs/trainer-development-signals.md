# Trainer Development Signals (P1.3)

## 1. Purpose

Evidence-only answer to "can current trainer capability support the
identified training need, based on available evidence?" Levels:

- `DEVELOPMENT_SIGNAL` — mapped capability does not cover the need;
- `SUFFICIENT_EVIDENCE` — mappings cover every teaching institution;
- `INSUFFICIENT_EVIDENCE` — no actionable priority to support (never a verdict).

Signal types name what was observed: `NO_TRAINER_OBSERVED`,
`LOW_TRAINER_COVERAGE`, `SKILL_TRAINER_MISMATCH`,
`TRAINER_CAPABILITY_OBSERVED`, `TRAINER_DATA_INSUFFICIENT`.

## 2. Inputs

P1.1 priorities (urgency/reasons), P1.2 proposals (linked per skill as
`related_proposals`), P0 #2 trainer/institution/course reads, and district
teaching sets derived from mapped course skills. A `trainer_skills` row IS
evidence; its absence is reported as absent evidence, never as inability
("absence of a mapping is not evidence of inability" is baked into the
reason strings).

## 3. Deterministic rules

For HIGH/MEDIUM skills: untaught + mapped somewhere → observed-ahead-of-
curriculum (sufficient); untaught + trainers present → mismatch; untaught +
zero trainers → absent. Taught + none mapped → mismatch if teaching
institutions have any trainers, else absent. Partial teaching coverage →
low coverage. Full teaching coverage → observed/sufficient. Anything without
an actionable priority → insufficient (never LOW/HIGH).

## 4. Privacy

Aggregates only — counts, institution counts, proficiency tallies. No
trainer ids, names, emails, or designations cross the boundary
(serialization-tested with identifying fixtures).

## 5. What is NOT built

Assignment, training plans, ratios, capability inference beyond mappings,
and any claim of the form "no trainer knows X".

## 6. API

`GET /api/v1/industry/trainer-development-signals` (district, role,
location/date/provider, course_id, skill, signal filters; existing auth),
ordered development-first then alphabetical. No persistence: live
projection.

## 7. Limitations

Mappings describe records, not measured capability; proficiency tallies are
descriptive; unmapped-role and unknown-district queries return empty
envelopes rather than uncontextualized rows.
