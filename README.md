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

INAURA/
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── assessment/
│   │   │   └── ui/
│   │   ├── pages/
│   │   ├── services/
│   │   └── ...
│   │
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

---

## Running Locally

### Backend

```bash
cd backend
python -m venv venv
```

#### Windows PowerShell

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

Backend:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

---

### Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

---

## Environment Variables

Create the required environment files based on the project's existing
configuration.

Typical frontend configuration:

```env
VITE_API_URL=http://localhost:8000/api/v1
```

Backend environment variables should contain the required Supabase and
external-service credentials.

Never commit `.env` files or API keys.

---

## Supabase

INAURA uses Supabase for persistent application data including:

- User/profile information
- Evidence records
- Analysis runs
- Skill assessments
- Skill results
- GitHub repository personalization
- Industry / role requirement data

Database migrations are stored under:

backend/supabase/

Run required migrations through the Supabase SQL editor when necessary.

---

## Testing

Run backend tests:

```bash
cd backend
pytest
```

Run frontend lint:

```bash
cd frontend
npm run lint
```

Build frontend:

```bash
npm run build
```

---

## Current Status

### Implemented

- [x] React + Vite frontend
- [x] FastAPI backend
- [x] Supabase integration
- [x] Authentication / user profile flow
- [x] Evidence collection
- [x] GitHub repository discovery
- [x] Multi-repository GitHub analysis
- [x] Deep repository inspection
- [x] Evidence validation
- [x] Canonical skill taxonomy
- [x] Skill scoring engine
- [x] Confidence calculation
- [x] Industry-grounded role requirements
- [x] O*NET / ESCO role mapping
- [x] Skill-gap analysis
- [x] Career-readiness calculation
- [x] Personalized roadmap
- [x] Skill assessments
- [x] Assessment-based validation
- [x] Evidence provenance
- [x] Repository-level personalization
- [x] AI-assisted repository marking
- [x] Repository exclusion
- [x] Downward-only skill override
- [x] Evidence-aware analysis

### Ongoing Refinements

- [ ] Expand assessment coverage across the canonical skill taxonomy
- [ ] Improve proficiency/confidence calibration using validation data
- [ ] Expand industry-role coverage
- [ ] Improve evidence explanations and provenance UX
- [ ] Improve personalization and adaptive assessment
- [ ] Continue improving false-positive filtering in repository analysis

---

## Important Design Principles

### Evidence ≠ Mastery

Finding a technology in a project does not automatically mean the user
masters it.

### Industry Requirements ≠ Candidate Evidence

Role requirements are sourced independently from the candidate's repositories
and profile.

### No Evidence ≠ Zero Ability

A 0% score means INAURA currently has no active evidence demonstrating the
skill.

### Users Cannot Inflate Their Scores

Users may reject or reduce an INAURA estimate, but they cannot manually
increase their proficiency.

### Assessment Is Validation

Direct assessment provides stronger evidence than project metadata alone.

### Explainability Matters

Every meaningful skill conclusion should be traceable to supporting evidence.

### Personalization Should Not Enable Score Manipulation

Users can exclude evidence or say that they do not currently know a skill,
but they cannot directly increase their score.

---

## Vision

INAURA aims to move beyond traditional resumes and static skill lists.

Instead of asking:

> What skills does this student claim to have?

INAURA asks:

> What evidence demonstrates these skills, how confident are we, what does
> the target role actually require, and what should the student learn next?

The goal is to create a career-readiness system that is:

- Evidence-driven
- Industry-grounded
- Explainable
- Personalized
- Auditable
- Resistant to inflated self-reporting

---

## Project Status

INAURA is an evolving prototype focused on evidence-driven,
industry-grounded career readiness.

Proficiency scores, confidence values, evidence weighting, assessments, and
role mappings are prototype heuristics unless validated against real-world
outcome data.

---

## License

Add the project's chosen license here.
