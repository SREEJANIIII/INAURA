# Human Review Workflow (P1.5)

## 1. Purpose

Turn P1.2 curriculum proposals into recorded human decisions — the first
phase with persistence, because decisions are historical state. Approval
records a decision only; it never implements, publishes, or edits curricula.

## 2. Transition graph

```
PENDING_REVIEW → APPROVED | REJECTED | DEFERRED
DEFERRED       → APPROVED | REJECTED | DEFERRED   (explicit re-review path)
APPROVED       → (terminal)
REJECTED       → (terminal)
```

No path back to PENDING_REVIEW, no REJECTED → IMPLEMENTED, and no
IMPLEMENTED state at all (approval is not implementation). The graph lives
in one named constant mirroring the outcome-service TRANSITIONS convention.

## 3. Decision rules

Proposals must exist in the live P1.2 projection for the given context
(404 otherwise — reviews attach to real proposals, never phantoms).
REJECTED and DEFERRED require a non-blank reason; APPROVED reasons are
optional. Terminal states reject further decisions (400); concurrent
decisions append rows with latest-wins, both rows preserved.

## 4. Reviewer and authorization

Reviewer is the authenticated caller (recorded server-side, never taken
from the payload). Limitation, documented honestly: the repository has no
institution-scoped admin role (employer owner/member is employer-scoped and
does not cover institutions), so any authenticated user may record a
decision. Fine-grained institutional RBAC is deferred, not invented here.

## 5. Audit trail

Append-only `curriculum_proposal_reviews` rows (migration 033): proposal
reference + snapshot (district/role/course/institution/skill/action),
reviewer, previous status (NULL = from PENDING_REVIEW), new status, reason,
timestamp. Current status = latest row, else PENDING_REVIEW. RLS:
authenticated SELECT, own-row INSERT only, no authenticated UPDATE/DELETE
(append-only), anon revoked, non-recursive policies.

## 6. API

`GET /industry/curriculum-reviews` (proposal/course/district/decision
filters), `POST /industry/curriculum-reviews` (201; validates proposal,
transition, and reason rules), `GET /industry/curriculum-reviews/{id}`
(current status + full history). No PATCH — re-review is a new POST.

## 7. Frontend

Proposal cards show live status badges with reviewer, timestamp, and
reason; terminal proposals hide controls; reject/defer require an inline
reason; approve posts directly. No Apply Curriculum button exists anywhere.

## 8. What is NOT built

Implementation workflows, IMPLEMENTED states, automatic curriculum
mutation, approval-gated publishing, institutional RBAC, and any LLM
involvement.
