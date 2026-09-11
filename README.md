# INAURA
### Bridging Skills to Industry

INAURA is a student career-readiness platform that analyzes a user's existing
evidence, compares demonstrated skills against industry-grounded role
requirements, identifies skill gaps, and generates a personalized learning
roadmap.

The platform is built around one core principle:

> Evidence should drive career-readiness decisions, not self-declared skills alone.

INAURA combines evidence from GitHub, competitive programming platforms,
projects, coursework, certifications, profiles, and direct skill assessments.

---

## Core Features

### Evidence-Based Skill Analysis

INAURA collects evidence from multiple sources and converts it into structured
skill signals.

Supported evidence sources include:

- GitHub
- LeetCode
- Codeforces
- Kaggle
- Projects
- Coursework / syllabus
- Certifications
- Resume
- LinkedIn
- Self-declared information
- INAURA skill assessments

Evidence is evaluated using source reliability, evidence depth, signal strength,
and contextual relevance rather than treating every source equally.

---

### Deep GitHub Repository Analysis

INAURA analyzes accessible repositories individually instead of relying only on
GitHub's visible language summary.

Repository analysis can inspect:

- Repository metadata
- Repository structure
- README / documentation
- Source files
- Imports and usages
- Dependency manifests
- Build configuration
- Framework configuration
- Tests
- Docker / container configuration
- CI/CD configuration
- Deployment / infrastructure artifacts

Evidence is evaluated by depth:

Documentation
    ↓
Metadata / language evidence
    ↓
Dependency / configuration evidence
    ↓
Source usage
    ↓
Implementation evidence
    ↓
Substantial implementation

Weak or incidental evidence is filtered before it becomes a meaningful skill
signal.

All accessible repositories are considered by the analysis pipeline, while
repository-level limits are used only to keep individual inspections practical.

---

### Evidence Validation

INAURA uses a deterministic evidence-validation layer to reduce false
positives.

A technology being mentioned somewhere in a README does not automatically
mean that the user demonstrated the skill.

Evidence is evaluated using factors such as:

- Evidence depth
- Context
- Corroboration
- Actual implementation
- Repository structure
- Tests / configuration
- Multiple independent repositories

This allows INAURA to distinguish between:

Mentioned
    ↓
Detected
    ↓
Supported
    ↓
Demonstrated

Only sufficiently supported evidence contributes meaningful skill signals.

---

### Skill Assessment

INAURA provides direct skill assessments for meaningful canonical skills.

Assessments use a versioned, curated question bank with deterministic grading.

The assessment layer provides a stronger form of validation than project
metadata alone.

Conceptually:

GitHub / Projects
        ↓
Supporting evidence
        ↓
Skill estimate
        ↓
INAURA Assessment
        ↓
Direct validation
        ↓
Updated proficiency + confidence

Assessment can increase or decrease a skill estimate depending on the result.

---

### Industry-Grounded Role Requirements

Role requirements are kept separate from candidate evidence.

INAURA uses industry-grounded occupational information as the basis for role
requirements and maps those concepts into its canonical skill taxonomy.

Current role modelling uses sources such as:

- O*NET
- ESCO

This creates a strict separation between:

Industry sources
    ↓
What the role requires

and:

Candidate evidence
    ↓
What the candidate demonstrates

A skill discovered in a candidate's portfolio does not automatically become a
requirement for the selected role.

---

### Skill Gap Analysis

For relevant role skills, INAURA calculates:

- Current proficiency
- Required proficiency
- Skill gap
- Confidence
- Priority

Core rule:

> No active evidence = 0% demonstrated proficiency.

A 0% result means that INAURA currently has no active evidence demonstrating
the skill. It does not mean the user is incapable of learning or performing
the skill.

Industry requirements define the target level; they never become candidate
proficiency.

---

### Personalized Roadmap

Skill gaps are converted into prioritized learning opportunities.

Roadmap generation uses the existing gap and priority system rather than
producing a generic learning plan.

When evidence or assessment results change, the underlying skill state can be
recalculated and the roadmap can adapt accordingly.

---

### Repository-Level Personalization

Users can personalize GitHub evidence at repository level.

For each repository, users can:

- Include the repository
- Exclude the repository from scoring
- Mark the repository as AI-assisted / heavily vibe-coded

Repository controls are independent.

Example:

Repository A → Included
Repository B → Included + AI-assisted
Repository C → Excluded

Raw evidence is preserved even when a repository is excluded from active
scoring.

AI-assisted status reduces the repository's scoring contribution while
preserving the evidence and its provenance.

---

### Safe Skill Overrides

Users can reject INAURA's current estimate using:

> I don't know this yet

This is intentionally a downward-only control.

Users cannot manually increase a proficiency percentage.

A skill can move upward only through:

- New valid evidence
- Stronger verified evidence
- Direct INAURA assessment

A previous zero override can be superseded by new evidence or a new assessment
without deleting historical data.

---

### Evidence Provenance

INAURA is designed to answer:

> Why did INAURA give me this score?

Each skill can expose contributing evidence, including where available:

- Source type
- Repository
- Repository URL
- Artifact / file
- Evidence depth
- Signal strength
- Source reliability
- Assessment result

This makes the analysis traceable instead of presenting unexplained
black-box percentages.

---

## Architecture

                       ## Project Structure

```text
INAURA/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── assessment/
│   │   │   └── ui/
│   │   ├── pages/
│   │   ├── services/
│   │   └── ...
│   ├── vite.config.ts
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── services/
│   │   │   ├── assessment/
│   │   │   ├── evidence/
│   │   │   ├── skill_engine.py
│   │   │   ├── signal_extractor.py
│   │   │   ├── industry_service.py
│   │   │   ├── analysis_run_service.py
│   │   │   └── ...
│   │   └── main.py
│   │
│   ├── supabase/
│   ├── tests/
│   └── requirements.txt
│
└── README.md
```

---

## End-to-End Flow

1. User provides evidence
        ↓
2. INAURA validates the evidence source
        ↓
3. GitHub repositories are discovered
        ↓
4. Repositories are inspected individually
        ↓
5. Repository artifacts produce candidate evidence
        ↓
6. Evidence-validation layer filters weak/false-positive signals
        ↓
7. Skills are normalized to the canonical taxonomy
        ↓
8. Evidence is aggregated across repositories and sources
        ↓
9. Industry role requirements are loaded
        ↓
10. Proficiency and confidence are calculated
        ↓
11. Skill gaps are calculated
        ↓
12. Priority is calculated
        ↓
13. Career readiness is calculated
        ↓
14. Personalized roadmap is generated
        ↓
15. User may assess selected skills
        ↓
16. Assessment results become additional evidence
        ↓
17. Analysis is recalculated

---

## Data Sources

INAURA keeps industry requirements separate from candidate evidence.

### Industry / Role Requirements

Role requirements are grounded using occupational skill frameworks such as:

- O*NET — Software Developers occupational information
- ESCO — European Skills, Competences, Qualifications and Occupations

These sources are used to identify skills and competencies relevant to a
target occupation.

INAURA maps the external concepts into its own canonical skill taxonomy.

Where INAURA performs its own mappings, weights, or interpretations, these
are explicitly treated as prototype heuristics rather than universal industry
standards.

### Candidate Evidence

Candidate evidence can come from:

- GitHub
- LeetCode
- Codeforces
- Kaggle
- Projects
- Coursework / syllabus
- Certifications
- Resume
- LinkedIn
- Self-declared skills
- INAURA direct skill assessments

### Assessment Data

INAURA assessments use a curated, versioned question bank.

Questions are designed around defined skill competencies and are graded
deterministically.

The assessment system does not require an LLM to assign the final score.

---

## Evidence Reliability

INAURA intentionally does not treat all evidence sources equally.

Current prototype hierarchy:

| Evidence Source | Reliability Tier |
|---|---|
| INAURA Assessment | Very High |
| LeetCode / Codeforces / Kaggle | High |
| Coursework / Academic Assessment | High |
| GitHub / Project Evidence | Medium |
| Certifications | Medium |
| Resume / LinkedIn / Self-declared | Low |

GitHub is deliberately treated as supporting evidence because a repository can
be AI-assisted and because project evidence demonstrates implementation more
reliably than it demonstrates individual mastery.

Evidence quality and source reliability remain separate concepts.

---

## Evidence vs Requirement

The system maintains a strict distinction:

Industry Source
    ↓
What is required for the role

Candidate Evidence
    ↓
What the user has demonstrated

Assessment
    ↓
What the user can directly demonstrate

Skill Engine
    ↓
Proficiency + Confidence + Gap

Gap Analysis
    ↓
Priority + Career Readiness

Roadmap
    ↓
Personalized learning plan

---

## Technology Stack

### Frontend

- React
- Vite
- TypeScript
- React Router
- CSS

### Backend

- Python
- FastAPI
- Uvicorn
- Pydantic

### Database

- Supabase
- PostgreSQL

### Evidence / External Data

- GitHub API
- LeetCode
- Codeforces
- Kaggle
- O*NET
- ESCO

### Testing

- Pytest
- FastAPI TestClient
- ESLint
- Vite production build

---

## Project Structure

```
Inaura/
├── frontend/          # React + Vite + TypeScript
│   ├── src/
│   │   ├── pages/          Landing.tsx, Home.tsx, ProfileSetup.tsx, Analysis.tsx, AnalysisResults.tsx, Roadmap.tsx, Dashboard.tsx, Login.tsx, Signup.tsx
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/  # api.ts, healthService etc.
│   │   └── ...
│   └── vite.config.ts # proxy /api -> FastAPI
└── backend/           # FastAPI + Python
    ├── app/
    │   ├── main.py    # entrypoint
    │   └── api/
    └── requirements.txt
```

## Prerequisites

- Node.js >= 18, npm >= 9
- Python >= 3.10, pip

## Running Locally

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
```

#### Windows PowerShell

```powershell
.\venv\Scripts\Activate.ps1
# or cmd: venv\Scripts\activate.bat
pip install -r requirements.txt
```

Run FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

Health check: http://localhost:8000/api/v1/health
Docs: http://localhost:8000/docs

### Frontend (Vite)

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173
Configure backend URL via env:

```bash
# frontend/.env
VITE_API_URL=http://localhost:8000/api/v1
```

Vite dev proxy also forwards `/api` to `http://localhost:8000` for local dev without CORS.

## Verification (Phase 0/1)

1. Backend health: `curl http://localhost:8000/api/v1/health`
2. Frontend: Home page has "Check Backend Connection" button — should show `ok` when backend is running.
3. Frontend build: `npm run build`
4. Backend check: `python -m py_compile app/main.py` or `pytest` when tests exist.

## Current Phase

- [x] Phase 0 — Skeleton fixed (main.py, requirements, git, README, title)
- [x] Phase 1 — Frontend ↔ Backend connection (api service, CORS, proxy, Home shell)
- [x] Phase 2 — Scoring engine (next)
- [x] RAG / Recommendation / Roadmap / Auth / DB — deferred
