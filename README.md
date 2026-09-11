# INAURA — Bridging Skills to Industry

**Evidence-driven career-readiness platform that turns verified GitHub, coding-platform, project, and certification evidence into an auditable skill gap and roadmap — not self-reported claims.**

> `0% if no evidence` · `deterministic skill engine` · `repository-level personalization` · `high-precision GitHub analysis` · `assessment-validated proficiency`

---

## Table of Contents
- [Why INAURA](#why-inaura)
- [Live Architecture](#live-architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Supabase — Database & Migrations](#supabase--database--migrations)
- [Running Locally](#running-locally)
- [API Reference](#api-reference)
- [Evidence Pipeline](#evidence-pipeline)
- [Deep GitHub Analysis](#deep-github-analysis)
- [Generic Evidence-Validation Gate](#generic-evidence-validation-gate)
- [Skill Engine & Gap Analysis](#skill-engine--gap-analysis)
- [Per-Repository Personalization](#per-repository-personalization)
- [Assessment System](#assessment-system)
- [Frontend Pages & Services](#frontend-pages--services)
- [Testing](#testing)
- [Diagnostics & Observability](#diagnostics--observability)
- [Verification Checklist](#verification-checklist)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [Contributing & License](#contributing--license)

---

## Why INAURA

Traditional career platforms trust self-declared skills. INAURA does the opposite:

1. **Collect evidence** – GitHub profile/URL, LeetCode/Codeforces/Kaggle/LinkedIn, resume/syllabus PDF/DOCX, manual projects & certifications.
2. **Verify each evidence independently** via its provider (GitHub API tree+content, LeetCode GraphQL/HTML, etc.) and persist `verified_signals` + `inspection` + `evidence_pipeline_version`.
3. **Extract signals deterministically** (`signal_extractor`) – no LLM for scoring – and normalize to a single canonical taxonomy (`skill_taxonomy`).
4. **Aggregate without inflation** – one signal per canonical skill per repository, then one aggregated signal per skill across repositories.
5. **Validate generically** (`github_validation` gate) – documentation-only, metadata-only, or soft-skill-from-code is rejected; only `SUPPORTED/DEMONSTRATED` reaches the engine.
6. **Score ethically** – if no accepted evidence, `proficiency=0, confidence=0, gap=required_level`. Industry `required_level` never leaks into `current`.
7. **Explain provenance** – every skill shows *which repositories, which files, which evidence depth* caused it.
8. **Let assessment validate** – GitHub is supporting evidence (`reliability 0.40`); INAURA assessment is `0.95` and can supersede overrides.

---

## Live Architecture

```
┌─────────────────────────┐
│  React 19 + Vite 8 + TS │  frontend/src
│  react-router 7          │  pages: Landing, Home, ProfileSetup, Analysis, AnalysisResults, Roadmap, Login/Signup
│  Supabase Auth (SSR)     │  components: landing, assessment/AssessmentModal, layout/Navbar
└──────────┬──────────────┘  services: api.ts, evidence.ts, analysis.ts, assessment.ts, profile.ts, roadmap.ts
           │  fetch + JWT
           ▼
┌─────────────────────────┐
│  FastAPI 0.1.0          │  backend/app/main.py  CORS: 5173/3000
│  /api/v1  + /docs       │  api/v1/router.py → 7 routers
│  JWT: Supabase service_role or HMAC fallback
└──────────┬──────────────┘
           │
┌──────────▼──────────────┐
│  Services Layer         │  profile_service · evidence_service · industry_service
│  · evidence/*           │  github.py (deep content), leetcode.py, codeforces.py, kaggle.py, linkedin.py, manager.py
│  · github_validation.py │  EvidenceDepth L0-L4, ContentBudget, SKIP vendor, PRIORITY impl
│  · signal_extractor.py  │  evidence → canonical signals
│  · skill_taxonomy.py    │  RAW_TAXONOMY 70+ skills (Programming, Frontend, Backend, DB, DevOps, AI/ML…)
│  · skill_engine.py      │  proficiency weighted-avg + unvalidated prior, confidence, gap, priority, quadrants
│  · evidence_weights.py  │  SOURCE_RELIABILITY (assessment 0.95 > leetcode 0.85 > github 0.40 > self 0.30)
│  · analysis_run_service │  orchestrator: profile → evidence → signals → repo-personalization → assessment → normalize → aggregate → req_map → overrides → assessments → gaps → readiness → persist
│  · roadmap_service      │  gap → prioritized items/milestones
│  · assessment/*         │  question_bank.py, service.py (VERY_HIGH reliability)
└──────────┬──────────────┘
           │
┌──────────▼──────────────┐
│  Supabase (Postgres +   │  supabase/*.sql 001-015, Storage bucket user-evidence
│  Auth + Storage)        │  tables: profiles, evidence, projects, certifications, skills, analysis_state/results, skill_assessments/gaps/signals, user_skill_overrides, user_github_repo_settings
└─────────────────────────┘
```

**Request flow `Start INAURA Analysis`:**
`POST /api/v1/analysis/run {target_role} → load_profile → load_evidence → ensure_file_evidence_parsed → auto-verify stale (pipeline version) → extract_skill_signals → adjust_github_signals_for_repo_settings → load_assessment_signals → normalize → aggregate → build_requirements_map → load_user_overrides → calculate_assessments → calculate_gaps → calculate_readiness → persist_analysis → return`.

---

## Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Frontend | React 19, TypeScript 6, Vite 8, react-router 7 | `@vitejs/plugin-react`, `tsc -b` |
| Auth | `@supabase/supabase-js` + `@supabase/ssr` | JWT attached in `api.ts:apiFetch` |
| Backend | FastAPI, Uvicorn[standard], Pydantic, pydantic-settings | `app/main.py`, `HTTPAuthorizationCredentials` |
| DB/Auth/Storage | Supabase | `supabase` py client, `get_supabase_client()` (service_role) |
| Evidence | `httpx`, `pypdf`, `python-docx`, `langchain-google-genai` (experimental ai_review_test) | GitHub tree+raw, LeetCode GraphQL, etc. |
| Config | `python-dotenv`, `pyjwt` | `core/config.py`, `core/supabase.py` |
| Tests | `pytest`, `anyio`, `httpx` Mock | `backend/tests/` 19 files, `FakeGitHub` |

---

## Project Structure

```
INAURA/
├── frontend/
│   ├── src/
│   │   ├── pages/          Landing.tsx, Home.tsx, ProfileSetup.tsx, Analysis.tsx, AnalysisResults.tsx, Roadmap.tsx, Dashboard.tsx, Login.tsx, Signup.tsx
│   │   ├── components/
│   │   │   ├── landing/ Hero, HowItWorks, EvidenceDriven, IndustryAlignment, Problem, FinalCTA
│   │   │   ├── assessment/ AssessmentModal.tsx/.css
│   │   │   ├── layout/ Navbar, Footer
│   │   │   └── ui/ Button, Container, Section
│   │   ├── services/       api.ts (apiFetch, JWT), evidence.ts, analysis.ts, assessment.ts, profile.ts, health.ts, industry.ts, roadmap.ts
│   │   ├── context/ AuthContext.tsx
│   │   ├── lib/ supabase.ts
│   │   ├── App.tsx, main.tsx, index.css, App.css
│   │   └── vite.config.ts  proxy /api → http://localhost:8000
│   ├── index.html, public/, eslint.config.js, tsconfig*.json
│   └── package.json
└── backend/
    ├── app/
    │   ├── main.py
    │   ├── core/           config.py, supabase.py, security.py (get_current_user)
    │   ├── api/v1/
    │   │   ├── router.py
    │   │   └── endpoints/  profile.py, evidence.py (github-repos before /{evidence_id}), industry.py, analysis.py, assessment.py, roadmap.py, ai_review_test.py
    │   ├── schemas/        evidence.py, profile.py, analysis.py, assessment.py, roadmap.py
    │   └── services/
    │       ├── evidence/   base.py (EVIDENCE_PIPELINE_VERSION=3, EvidenceDepth), github.py, github_validation.py, leetcode.py, codeforces.py, kaggle.py, linkedin.py, manager.py, url_utils.py
    │       ├── analysis_run_service.py, signal_extractor.py, skill_taxonomy.py, skill_engine.py, evidence_weights.py, profile_service.py, evidence_service.py, industry_service.py, retrieval_service.py, roadmap_service.py, document_parser.py
    │       └── assessment/ question_bank.py, service.py
    ├── supabase/
    │   ├── 001_create_profiles.sql … 015_github_repo_personalization.sql (see below)
    │   └── 014_software_engineer_onet_esco.sql
    ├── tests/              test_github_deep_evidence.py, test_github_profile.py, test_github_false_positive.py (14 fixtures A-M), test_provenance_personalization.py, test_deep_audit.py, …
    ├── requirements.txt, .env.example, diag.py, live_verify.py
    └── venv/
```

---

## Prerequisites

- Node.js ≥ 18, npm ≥ 9
- Python ≥ 3.10, pip, `venv`
- Supabase project (URL + `anon` key for frontend, `service_role` key + `JWT_SECRET` for backend)
- Optional `GITHUB_TOKEN`/`GH_TOKEN` for higher GitHub rate limits (anonymous still works, paginated `per_page=100`, `MAX_PROFILE_PAGES=50`)

---

## Environment Variables

**`backend/.env`** (never commit `service_role`):
```ini
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon>
SUPABASE_SERVICE_ROLE_KEY=<service_role>
SUPABASE_JWT_SECRET=<jwt_secret>
FRONTEND_URL=http://localhost:5173
# optional
GITHUB_TOKEN=ghp_xxx
# optional RAG
EMBEDDING_PROVIDER=
EMBEDDING_API_KEY=
```

**`frontend/.env`**:
```ini
VITE_API_URL=http://localhost:8000/api/v1
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon>
```

`Vite dev proxy` also forwards `/api` → `8000` so `CORS` is not required in dev.

---

## Supabase — Database & Migrations

Apply in order in Supabase SQL Editor (idempotent `create table if not exists` + `grant` + `RLS`):

| File | Purpose |
|------|---------|
| `001_create_profiles.sql` | `profiles` + RLS `auth.uid()=user_id` |
| `002_create_evidence.sql` | `evidence`, `projects`, `certifications`, bucket `user-evidence` |
| `003_industry_knowledge.sql` | `industry_roles`, `industry_requirements` |
| `004_analysis_state.sql` | `analysis_state` (`target_role`, `status`) |
| `005_skill_engine.sql` | `skills`, `analysis_results`, `skill_assessments`, `skill_gaps`, `skill_signals` |
| `006_roadmap.sql` | `roadmaps`, `roadmap_items`, `milestones` |
| `007_canonical_skills.sql` | canonical seed (70+ from `skill_taxonomy.RAW_TAXONOMY`) |
| `008_evidence_verification.sql` | `verification_status`, `verified_signals`, `provider`, `evidence_pipeline_version` |
| `009_industry_intelligence.sql` | RAG retrieval index |
| `010_evidence_enhancements.sql` | file parsing `parsed_text/sections`, `handle_updated_at` |
| `011_gap_analysis_engine.sql` | `priority_score`, `gap_type`, quadrants |
| `012_skill_assessment.sql` | `assessments`, `assessment_attempts` (`assessment-v1`) |
| `013_evidence_provenance_and_personalization.sql` | `user_skill_overrides` (downward zero only) |
| `014_software_engineer_onet_esco.sql` | O*NET/ESCO Software Engineer requirements |
| `015_github_repo_personalization.sql` | `user_github_repo_settings` (`repo_full_name` lower, `is_excluded`, `is_ai_assisted` default false) + trigger + `GRANT authenticated,service_role` |

Check:
```sql
select * from user_github_repo_settings limit 1;
select evidence_pipeline_version from evidence limit 1;
```

---

## Running Locally

**Backend:**
```bash
cd backend
python -m venv venv
# Windows PowerShell
.\venv\Scripts\Activate.ps1
# cmd
venv\Scripts\activate.bat
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Health
curl http://localhost:8000/api/v1/health
# Docs
open http://localhost:8000/docs
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build
npm run lint
```

Login → `ProfileSetup` → `Analysis` (add GitHub/LeetCode/… + projects/certs) → `Start INAURA Analysis` → `AnalysisResults` (quadrants, gaps, `Why this score?` drawer, `Evidence Sources — Personalization Controls` per-repo `Included/Excluded` + `AI-assisted`) → `Roadmap`.

---

## API Reference

Base `http://localhost:8000/api/v1`, JWT `Authorization: Bearer <supabase_access_token>`.

**Evidence** `prefix /evidence` – note `GET /github-repos` is *before* `/{evidence_id}` to avoid shadowing `evidence_id="github-repos"` → `500 invalid uuid`:
- `GET    /evidence` `list_evidence`
- `POST   /evidence` `create_evidence`
- `PUT    /evidence/{evidence_id}`
- `DELETE /evidence/{evidence_id}`
- `POST   /evidence/{evidence_id}/verify` / `POST /evidence/{evidence_id}/reparse`
- `POST   /evidence/upload` (multipart `evidence_type`, `file`)
- `GET    /evidence/projects` / `POST` / `DELETE /projects/{project_id}`
- `GET    /evidence/certifications` / `POST` / `DELETE /certifications/{cert_id}`
- `POST   /evidence/{evidence_id}/exclude` / `ai-assisted` (evidence level)
- `POST   /evidence/projects/{project_id}/exclude|ai-assisted`
- `POST   /evidence/certifications/{cert_id}/exclude`
- `GET    /evidence/github-repos` → `{full_name,name,url,html_url,is_excluded,is_ai_assisted,classification,fork,archived,pushed_at,evidence_id}[]` (safe defaults `false`, per-repo `try/except`, dedup)
- `POST   /evidence/github-repos/exclude` `{repo_full_name,is_excluded}`
- `POST   /evidence/github-repos/ai-assisted` `{repo_full_name,is_ai_assisted}`
- `GET    /evidence/summary` `{total_sources:9, provided, evidence, projects, certifications}`

**Profile** `/profile` `GET /me`, `POST /setup`, `PUT /me`.

**Analysis** `/analysis`: `GET /state`, `POST /target`, `POST /prepare`, `POST /run` (orchestrator), `GET /latest`, `GET /skills`, `GET /gaps` (enriched with `evidence_sources`, `evidence_state`), `GET/POST /skill-overrides`, `DELETE /skill-overrides/{skill_key}`.

**Assessment** `/assessment`: `GET /available`, `POST /start`, `POST /submit`, `GET /history`.

**Roadmap** `/roadmap`: `GET /latest`, `GET /items`, `POST /items/{id}/complete`.

**Health** `GET /health`.

`apiFetch` (`frontend/src/services/api.ts`) injects Supabase `access_token` and unwraps `500` as `API error 500 … {"detail":…}`.

---

## Evidence Pipeline

```
evidence (github|leetcode|codeforces|kaggle|linkedin|resume|syllabus|certification_file|project_doc)
  → provider.verify() → VerificationResult {status, signals: ExtractedSignal[], raw_metadata: inspection, verified_at}
  → evidence_service.verify_evidence_item() persists {verification_status, verified_signals, inspection, evidence_pipeline_version=3}
  → signal_extractor.extract_signals() (skips is_excluded, dedup via get_evidence_dedup_key, file aspirational filter, project dedup vs inspected_github_repos)
  → make_signal() (source_reliability via evidence_weights, AI halved)
```

Each `ExtractedSignal` = `{skill, signal_strength, depth (L0-L4), reason, source_reliability, metadata: {evidence_kind, repositories, ...}}`.

---

## Deep GitHub Analysis

**Discovery vs Content (separate stages):**

- *Discovery* cheap: `GET /users/{owner}/repos?per_page=100&page=N&sort=updated` looped to `MAX_PROFILE_PAGES=50` (5,000 repos), dedup by `id/full_name`, handles `404` first page, rate-limit (`x-ratelimit-remaining/reset`), `link rel="next"`. Never truncated to 5.

- *Content* expensive, bounded per-repo (`MAX_CONTENT_FETCHES_PER_REPO = 1 + 6 + 3 =10`) + profile-wide `ContentBudget=600`: tree `GET /repos/{o}/{r}/git/trees/{branch}?recursive=1` (capped 3,000 entries, 800 `top_files`), `GET /languages`, `GET /contents`, `GET /contents/.github/workflows`, `raw.githubusercontent` for `README` (`20k`), sampled sources (`40k` each, `200k` bytes skip, `SKIP_PATH_MARKERS` vendor/build), configs (`12k` each), manifests (`pyproject→pyproject`, `go.mod→gomod`, … up to `MAX_EXTRA_MANIFEST_FETCHES=4`), `select_source_files` round-robins across extensions prioritizing `src/app/lib` + `main/app/index`.

**Artifacts inspected per eligible repo:** tree, source files (imports via `IMPORT_PATTERNS` → `skill_mention_counts`/`import_skill_counts`), dependency manifests, `package.json`/`requirements.txt`, `Dockerfile`/`docker-compose`, `.github/workflows`, `k8s` markers, `Terraform` `.tf`, test counts, `has_workflows/ci/k8s`.

**Depth:** `URL 0` < `mention 1 (0.40)` < `config/dependency 2 (0.60)` < `implementation 3 (0.75)` < `substantial 4 (0.85)`; fork caps to `L2` & `0.55`, archived discounts to `0.70`.

---

## Generic Evidence-Validation Gate

`evidence/github_validation.py` – no `if skill=="Docker"` hacks.

- **Per-repo** `validate_repo_signal`: reject `Soft Skills` (`soft_skill_not_from_code`); keep `documentation` as weak (filtered later).
- **Aggregated** `validate_aggregated_signal`:

  - `Soft Skills` always reject.
  - `documentation_only && depth==1` → `documentation_only`.
  - `kinds==["documentation"] && depth==1` → `documentation_only`.
  - `!kinds && depth==1` → `insufficient_corroboration`.
  - Programming `depth<3` without `implementation/source_usage` → `insufficient_corroboration`.
  - Frontend/Backend single `dependency` without `source_usage/implementation` and `repo_count<2` → `insufficient_corroboration`.
  - Single fork weak `owned==0 && repo_count==1 && depth<=2` for programming → `insufficient_corroboration`.

Rejected kept as `inspection.rejected_candidates`/`rejected_count` + `raw_metadata.github_candidates_{detected,accepted,rejected}` for diagnostics; explainability retains `skill, repository, artifact/file, evidence_kind, depth, strength, reason` and `rejected` reason (`documentation_only`, `soft_skill_not_from_code`, `insufficient_corroboration`, `insufficient_context`, `incidental_match`).

Result on live `SREEJANIIII` 18 repos: `candidates 38 → accepted 23 → rejected 15` (15 doc-only `Next.js/CSS/Deployment/...` correctly filtered, 23 strong like `Python 0.85 depth4, REST APIs depth4, Docker` via real `Dockerfile` kept).

---

## Skill Engine & Gap Analysis

`skill_taxonomy.RAW_TAXONOMY` 70+ skills `category: Programming|Frontend|Backend|Databases|DevOps/Cloud|AI/ML|Cybersecurity|Mobile|Tools|Quality|Soft Skills`.

`evidence_weights.SOURCE_RELIABILITY`: `assessment 0.95` > `leetcode/codeforces/kaggle 0.85, syllabus 0.80` > `github/project 0.40, certification 0.55` > `self_declared 0.30`; `tier_of()`; `validation_strength()`.

`skill_engine`: `proficiency` weighted avg `Σ strength*reliability / Σ reliability` with `proficiency_with_prior` shrinking artifact-only high estimates toward not-validated; `confidence_from_signals`; `gap = max(0, required - proficiency)`; `calculate_prioritized_gap` (`gap * importance * demand * interview * (1-confidence)`); `classify_skill_quadrant` (`strong_validated|unverified_claim|confirmed_gap|exploratory`); `aggregate_*_component` + `readiness = 0.45*skill +0.25*industry +0.30*evidence`.

`analysis_run_service` ethical: if `evidence_count==0 && !has_assessment` → `proficiency=0, confidence=0, gap=required, gap_type=evidence_gap, evidence_state=no_evidence`. Overrides timestamp-aware supersede.

---

## Per-Repository Personalization

`user_github_repo_settings` (`repo_full_name` lower, `is_excluded`, `is_ai_assisted`).

- `GET /github-repos` merges `repo_settings` map with safe defaults `false`; deduplicates by `full_name` lower.
- `POST /github-repos/exclude|ai-assisted` upserts `{repo_url: https://github.com/{lower}}`, triggers `run_analysis` if `target_role` exists.
- `adjust_github_signals_for_repo_settings(signals, repo_settings)`: drops excluded repo from `repositories`, halves reliability proportionally for AI (`factor = 1 -0.5*ai_ratio`), preserves `original_repo_count`.
- Project/cert exclusion similarly via `evidence_service`.

---

## Assessment System

`backend/app/services/assessment/question_bank.py` `assessment-v1` (≥5 skills), `service.py` `build_assessment_signals`, `select_assessable_skills`. `POST /assessment/start` → `POST /submit` → signal `source=assessment` `reliability 0.95` (`VERY_HIGH`), separate provenance `Validated by assessment`. Downward zero-override only (`is_zero_override=true`) preserved historically, superseded by newer evidence/assessment.

---

## Frontend Pages & Services

- `Landing` → `HowItWorks` → `EvidenceDriven` → `IndustryAlignment` → `FinalCTA`.
- `AuthContext` + `ProtectedRoute` (Supabase SSR).
- `Home` – backend health check.
- `ProfileSetup` – college/branch/year/interests.
- `Analysis` – evidence forms + `Verify` + `Prepare` + `Run`.
- `AnalysisResults` – `readiness`, `strengths`, `priority gaps`, `evidence gaps`, LeetCode DSA `pillar_breakdown`, quadrants, skill table (`Current/Required/Gap/Confidence/Evidence/Priority`), `Why this score?` drawer (requirement provenance O*NET/ESCO), `Assessment` `Assess/Re-verify`, `I don't actually know this yet` (zero-override), `Evidence Sources — Personalization Controls` (per-repo toggle + `AI-assisted` checkbox, fork badge, `Classification: owned_active`).
- `Roadmap` – `roadmap_items`/`milestones`.
- Services `api.ts` (`API_BASE_URL` `VITE_API_URL` fallback `http://localhost:8000/api/v1`, `params` helper, `Authorization` header, `Content-Type` JSON vs `FormData`, `204` handling).

---

## Testing

```bash
cd backend
.\venv\Scripts\python -m pytest tests/test_github_deep_evidence.py -v        # 23: pagination, old repos, content budget, depth, aggregation bounds, reliability
.\venv\Scripts\python -m pytest tests/test_github_profile.py -v              # 13: single/multi 137-page, beyond 5, zero, fork/archived, rate-limit, provenance
.\venv\Scripts\python -m pytest tests/test_github_false_positive.py -v       # 14: A-M fixtures doc-only, lang-only, dep-only, dep+usage, src+tests, incidental, vendor, repeated weak, multi-impl corroborated, multi-doc weak, good preserved, zero, assessable, soft
.\venv\Scripts\python -m pytest tests/test_provenance_personalization.py -v  # 23: zero-evidence 0%, no leak, provenance, overrides, exclusion, AI half, portfolio not inflate
.\venv\Scripts\python -m pytest tests/test_deep_audit.py -v                  # 19: All repos enumerated, provenance, Java impl, multiple agg, per-repo state
.\venv\Scripts\python -m pytest -q                                            # 92+ overall
```

`FakeGitHub` mocks `httpx.AsyncClient.get` for pagination (`link` header), languages, `git/trees`, `raw` fetch, vendor filtering, fork/archived/rate-limit.

Run `live_verify.py` for real pipeline counts (`repositories_discovered/attempted/inspected/with_evidence/contributing`, `github_candidates_detected/accepted/rejected`).

---

## Diagnostics & Observability

- Provider `raw_metadata`: `repositories_fetched/inspected/failed/skipped`, `owned/forked/archived/active`, `repositories_content_analyzed`, `content_fetches_used/budget`, `github_candidates_detected/accepted/rejected`, per-repo `inspection: {source_files_sampled, import_tokens, config_files_sampled, content_fetches, content_budget_exhausted, candidates_detected/accepted, rejected_candidates}`.
- Analysis `github_diagnostics` (from `_compute_github_diagnostics`): same + `repositories_contributing_skills`.
- Each final skill `evidence_sources: {source_label, source_type, strength, reliability, details:{repositories:[{name,full_name,url,fork,archived,classification,depth,signal_strength}], repo_count, evidence_depth, evidence_kinds, languages}}` + `is_ai_assisted`.
- Rejected candidates retain `skill, depth, evidence_kind, reason`.

---

## Verification Checklist

1. `curl http://localhost:8000/api/v1/health` → `{"status":"ok"}`
2. `GET /evidence/github-repos` → `200`, 18 repos, `is_excluded`/`is_ai_assisted` present, missing defaults `false`, one malformed repo doesn't 500.
3. `POST /github-repos/ai-assisted` → `200` → `GET` shows `true` → toggle `false` persists.
4. `pytest` all green, `npm run build` succeeds.
5. `SREEJANIIII/StonePaperScissors` (2025-10-09) beyond first 5 → `inspected`, `game.js` sampled, `Git` depth 3 present.
6. `SREEJANIIII/INAURA` → `src/main.py` `fastapi` + `requirements.txt` → `Python` depth 4, `REST APIs` depth 3.

---

## Deployment

- Set `FRONTEND_URL` in `app/main.py` CORS `allow_origins`.
- Supabase RLS already `auth.uid()=user_id`; `grant` to `authenticated, service_role`.
- `GITHUB_TOKEN` optional but recommended for profile inspection (600 fetches budget).
- No LLM calls in scoring path; cost bounded per-repo `ContentBudget`.

---

## Roadmap

- [x] Skeleton, Auth, Evidence CRUD, Verification, File parsing (`pypdf`/`python-docx`), Industry RAG, Skill engine v1, Assessment `v1`, Per-repo personalization, Deep GitHub content, Validation gate `v3`
- [ ] Roadmap progress tracking, `progress` table, `ai_review_test` promotion, E2E Cypress

---

## Contributing & License

1. `git checkout -b feat/<scope>`
2. Keep `skill_taxonomy` single source; add `aliases` not hardcodes.
3. Keep `evidence_weights` single source; don't change `github 0.40` in this layer.
4. Run `pytest` + `npm run lint` before PR.
5. PR must include `inspected_repos` count and `why this score?` screenshot.

License: Proprietary – SREEJANIIII/INAURA (educational prototype, heuristic model not validated proficiency measurement).

---

*INAURA `engine_version` shown in `AnalysisResults` header; `evidence_pipeline_version=3`; `benchmark: Industry Intelligence 2026.1 (ACM/IEEE, Stack Overflow, BLS, O*NET/ESCO)`.*

