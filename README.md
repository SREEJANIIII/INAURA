# INAURA
### Bridging Skills to Industry

INAURA is a student career-readiness platform that analyzes a user's existing
evidence, compares demonstrated skills against industry-grounded role
requirements, identifies skill gaps, and generates a personalized learning
roadmap.

The platform is designed around one core principle:

> **Evidence should drive career-readiness decisions, not self-declared skills alone.**

INAURA combines multiple evidence sources such as GitHub, competitive
programming platforms, projects, coursework, certifications, and direct skill
assessments.

---

## ✨ Core Features

### 🔍 Evidence-Based Skill Analysis

INAURA collects evidence from multiple sources and converts it into
structured skill signals.

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

Evidence is evaluated using source reliability, evidence depth, and signal
strength rather than treating every source equally.

---

### 🐙 Deep GitHub Repository Analysis

INAURA does not rely only on GitHub's displayed language statistics.

For accessible repositories, INAURA can inspect:

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

Repositories are processed individually and evidence is preserved at
repository level.

The system also distinguishes between:

```text
Documentation evidence
        ↓
Configuration / dependency evidence
        ↓
Source usage
        ↓
Implementation evidence
        ↓
Substantial implementation
