# Capacity Planning Signals (P1.4)

## 1. Purpose

Represent the evidence available (and missing) for capacity planning per
prioritized skill: observed institutions, courses, learners, and trainers —
plus an explicit statement that seat capacity is not measured. Planning
inputs, never prescriptions.

## 2. The capacity honesty rule

The repository contains no validated seat-capacity source (verified by
audit: no seat/centre/enrolment-capacity fields exist anywhere). Therefore:

- `capacity_status` is always `CAPACITY_DATA_INSUFFICIENT`;
- every row and response carries "Capacity recommendation unavailable:
  no validated capacity data.";
- `CAPACITY_DATA_AVAILABLE` exists in the vocabulary with an explicit gate
  (a validated source) and tests assert it never fires today;
- shortage states do not exist — a planning data gap is missing data, and
  missing data is never zero capacity and never an observed shortage.

## 3. Inputs (composed, never recomputed)

P1.1 priorities (urgency + evidence counts) and district training
intelligence (institutions, per-skill teaching coverage, learner totals).
No ratios (trainer-to-student or otherwise), no utilization, no seat
numbers, no required-trainer counts.

## 4. Privacy

Aggregates only (serialization-tested with identifying fixtures);
suppressed-learner contexts yield no rows.

## 5. API

`GET /api/v1/industry/capacity-planning` (district, role, location/date/
provider, course_id, skill filters; existing auth). No persistence: live
projection.

## 6. Limitations

Cannot answer "how many seats/trainers are needed" — by design, until
validated capacity data exists. Course scoping validates district
membership; rows remain district-level planning inputs.
