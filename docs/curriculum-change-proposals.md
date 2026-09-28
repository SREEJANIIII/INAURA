# Curriculum Change Proposals (P1.2)

## 1. Purpose

Deterministic, evidence-backed curriculum proposals: "given this observed
training priority, what curriculum change could reasonably address the
evidence?" Output is strictly human-reviewable planning artifacts:

```
P0 Evidence → P1.1 Priority → P1.2 Proposal → (P1.5) Human Review → update
```

## 2. Architecture

`curriculum_proposal_service` composes P1.1 priorities (urgency + reasons +
evidence) with per-course P0 #4 alignment rows (curriculum/attainment/demand
statuses, module names) and P0 #2 course/institution/module records. The
proposal unit is course + skill + priority context — one record per relevant
course, never a fake universal course. No migration: live projection with
deterministic `prop-<sha1>` ids (course + skill + action + role + district +
period + provider), so future P1.5 review can reference stable ids.

## 3. Inputs from P1.1

Priority level/status/reasons and the evidence packet per skill. LOW and
INSUFFICIENT_EVIDENCE entries never become proposals (informational only);
aligned skills produce nothing.

## 4. Action types

Controlled vocabulary — `ADD_SKILL` (missing + HIGH/MEDIUM),
`INCREASE_COVERAGE` (taught + weak + introductory/unstated coverage),
`ADD_PRACTICAL_ASSESSMENT` (taught + weak + intermediate/advanced coverage:
depth exists, demonstration is the gap), `UPDATE_MODULE` (declining demand
with moderate/strong attainment and a resolved real module),
`REVIEW_CONTENT` (gap without sufficient specificity: moderate/stable, or
declining without a resolvable module).

## 5. Deterministic rules

Precedence in `_select_action`, pure functions throughout, no LLM. Titles
and rationales are templates over evidence fields (trend/share/coverage/
modules/fallback flag + "Proposed for human review."). No placement,
employer-preference, or certainty claims; declining demand is framed as
"review is indicated, not removal", and "obsolete" appears nowhere.

## 6. Proposal status

Every record starts `PENDING_REVIEW`; no approval workflow exists yet, and
the API filter rejects any other status value. Nothing implies approval or
implementation.

## 7. Evidence

Each proposal carries the P1.1 evidence packet (market/curriculum/learner/
trainer blocks), a `current_state` snapshot, and a high-level
`proposed_change` (action, skill, course/module target, resolved module
ids/names only). No hours, sessions, seats, lesson text, questions, vendors,
or trainer assignments — the change shape is deliberately coarse.

## 8. Rationale generation

One sentence per evidence dimension actually present, each traceable (share
percentages interpolate the exact field value; coverage sentences cite the
 recorded level; fallback sentences cite the match type).

## 9. Market context

Role/location/provider/period ride along per proposal; global fallback is
stated in both rationale and context, never rewritten as district demand.

## 10. Privacy

Aggregates only (responses are serialization-scanned for user ids in tests);
suppressed-learner districts yield no proposals; unmapped concepts are
counted upstream and excluded.

## 11. Provenance

Engine version, timestamp, P1.1/alignment engine versions, district/role,
demand suppression flag, and the "planning artifact, does not modify
curriculum" note on every record.

## 12. API

`GET /api/v1/industry/curriculum-proposals` (district, role, location/date/
provider, course_id, skill, action_type, priority, status filters; existing
auth) plus `GET /.../curriculum-proposals/{proposal_id}` detail (404
outside context). Generation performs zero writes — statically asserted by
snapshotting the fake database around generation in tests.

## 13. Frontend

Additive `CurriculumProposals` section (district/state form → proposal cards
with action, title, course, evidence, PENDING REVIEW badge). Proposed is
visually distinct from approved/implemented, and there is no Apply button.

## 14. What the engine does NOT do

Modify curricula, approve/implement anything, author content, allocate
seats, assign or develop trainers, generate assessments, call LLMs, score
proposals numerically, or invent confidence values.

## 15. Future human review workflow

P1.5 will need proposal persistence (review status transitions,
approvals/rejections, implementation tracking) — only then is a migration
justified, storing references plus decisions rather than duplicated P0
evidence.

> "A curriculum proposal is a planning artifact and does not modify
>  curriculum data."
