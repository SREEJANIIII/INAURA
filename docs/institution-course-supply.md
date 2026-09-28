# Institution + Course + Curriculum Supply (P0 #2)

## 1. Why the model exists

Labour-market demand (P0 #1) says which skills industry needs. To act on that,
INAURA must also represent what institutions *teach*. This phase builds that
reliable supply-side foundation — nothing more:

```
Labour Market Demand
        ↓
   Required Skills
        ↓
Course Skill Supply      <-- this phase (P0 #2)
        ↓
   Alignment Engine      <-- later (NOT built here)
        ↓
  Course Skill Gaps      <-- later
        ↓
District Training Plan   <-- later
```

## 2. Institution → Course → Module → Skill

- **institutions**: training providers (ITI, Polytechnic, College,
  University, Skill Training Centre, Training Institute, Other) with
  structured district/state/country/city for future district aggregation.
- **courses**: belong to exactly one institution; unique per
  (institution, lower(name)). Free-text `level` (e.g. Diploma, Certificate),
  `duration_text` (e.g. "6 months"), constrained `delivery_mode`
  (online/offline/hybrid), `status` (draft/active/archived).
- **course_modules**: curriculum units with `sequence` (unique per course —
  curriculum ordering) and optional `hours`.
- **course_skills**: skills taught. `module_id` nullable → module-level or
  course-level skills. No duplicate mapping for the same
  course + module + canonical skill (service guard + partial unique indexes).

## 3. Trainer → Skill

Minimal roster (name/email/designation/status — not an HR system) plus
**trainer_skills**: one proficiency record per trainer + canonical skill.
Trainer skills must resolve to the canonical taxonomy (unmapped → 400).
Enables the future chain: required skill → course teaches it? → trainer can
teach it? The reasoning itself is NOT implemented here.

## 4. Canonical skill mapping

Single source of truth: `skill_taxonomy.get_canonical_skill`. No second
taxonomy, no duplicate mapping logic. Resolution is server-side: API callers
send raw `source_concept` phrases only, never `skill_id`. "React.js" /
"ReactJS" / "react" → `react`; "Flutter development" → `flutter`;
"FastAPI" → `rest_apis`. `skill_id` (uuid FK → `skills.id`) resolves
best-effort and stays null when the DB row is absent — the slug is the
stable identity.

## 5. Raw concept preservation

`source_concept` stores the verbatim curriculum phrase ("  React.js  " →
"React.js"). Raw text is never silently rewritten or discarded.

## 6. Unmapped concepts

No clean taxonomy match → `mapping_status='unmapped'`,
`canonical_skill_slug=NULL`, concept preserved (e.g. "Blockchain Basics").
Unmapped rows are excludable via `mapping_status` filter and never counted
as canonical supply. A DB check constraint enforces
mapped ⇔ slug-present. The demo seed intentionally includes one unmapped
concept to prove this path.

## 7. Provenance / demo data

`data_origin` reuses the repo-wide tiers
(source_data | inaura_derived | demo_seeded). Real records are `source_data`;
`build_demo_seed()` / `seed_demo_data()` produce the synthetic
"INAURA Demo Skill Training Centre" (3 courses, 13 modules, mapped skills +
1 unmapped concept, 2 trainers) with `data_origin='demo_seeded'` everywhere.
Demo data is never real government/institutional curriculum data. Seeding is
idempotent (matched by code/email unique keys; reruns skip).

## 8. API structure

`GET/POST /api/v1/institutions`, `GET/PATCH /api/v1/institutions/{id}`,
`POST/GET /institutions/{id}/courses`, `GET/PATCH /api/v1/courses/{id}`,
`POST/GET /courses/{id}/modules`, `POST/GET/DELETE-skill
/courses/{id}/skills`, `GET /courses/{id}/coverage` (which-skills-does-this-
course-teach view: course + module groups + course-level skills + counts),
`POST/GET /institutions/{id}/trainers`, `POST/GET/DELETE-skill
/trainers/{id}/skills`. Thin routes → `institution_service`; auth via the
existing `get_current_user` (no new auth system).

## 9. RLS / security model

Reference-data model (migration 031): authenticated users may SELECT;
INSERT/UPDATE/DELETE have no authenticated policies, so writes flow only
through the backend service-role client (same convention as migrations 029
and 030). `anon`/`PUBLIC` revoked. Policies are single-table
`auth.uid() IS NOT NULL` checks — no cross-table subqueries, so RLS cannot
recurse (static regression test asserts this over the migration text).

## 10. How this connects to P0 #1

Same philosophy, no coupling: canonical taxonomy reuse, raw-concept
preservation, unmapped marking, `demo_seeded` labelling, deterministic pure
functions (`build_demo_seed`, `resolve_skill`), service-layer guards with DB
constraints as backstop. `institution_service` does not import
labour-market or industry-intelligence modules. P0 #1 tests, gap
mathematics, O*NET/ESCO, and `DemoSeedDemandProvider` are untouched
(regression-tested).

## 11. Intentionally NOT implemented

Industry-demand comparison, course scoring/ranking, district
recommendations, curriculum optimization, AI curriculum rewriting, trainer
or capacity recommendations, cohort supply (P0 #3). The coverage view
exposes supply facts only — no demand math.
