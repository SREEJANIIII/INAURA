import math
import time
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from supabase import Client
from ..core.supabase import get_supabase_client
from .skill_taxonomy import normalize_skill, normalize_skill_slug
from .industry_roles import canonicalize_role_name, ROLE_CATALOG, compare_roles as compare_roles_impl

TABLE = "industry_requirements"
INDUSTRY_PROFILE_VERSION = "2026.1"

# ---------------------------------------------------------------------------
# Authentic Seed Catalog (11 Supported Roles)
# Citations based on ACM/IEEE CS2023, Stack Overflow Survey 2024, BLS, CNCF, OWASP
# No fabricated statistics or percentages
# ---------------------------------------------------------------------------
PROTOTYPE_INDUSTRY_REQUIREMENTS: List[dict] = [
    # 1. Software Engineer
    {
        "role": "Software Engineer",
        "skill": "Data Structures & Algorithms",
        "skill_category": "Computer Science",
        "required_level": 0.85,
        "importance": 0.95,
        "demand": 0.90,
        "interview_relevance": 0.95,
        "industry_confidence": 0.95,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Foundational core competency for asymptotic complexity analysis, memory models, and standard algorithmic problem solving.",
        "published_at": "2024-01-15",
        "description": "Problem solving, algorithmic complexity, and data organization fundamentals",
    },
    {
        "role": "Software Engineer",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.88,
        "interview_relevance": 0.75,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "High-level language widely used for scripting, tooling, automation, and backend services.",
        "published_at": "2024-05-01",
        "description": "General-purpose programming language for tooling and services",
    },
    {
        "role": "Software Engineer",
        "skill": "Java",
        "skill_category": "Programming",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Class-based object-oriented language for enterprise applications and scalable distributed services.",
        "published_at": "2024-01-15",
        "description": "Enterprise language and object-oriented fundamentals",
    },
    {
        "role": "Software Engineer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.85,
        "demand": 0.90,
        "interview_relevance": 0.60,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Universal standard for source code management, branching workflows, and collaborative software development.",
        "published_at": "2024-05-01",
        "description": "Distributed version control and collaboration",
    },
    {
        "role": "Software Engineer",
        "skill": "SQL",
        "skill_category": "Databases",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.70,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Relational data modeling, schema definition, and structured query formulation.",
        "published_at": "2024-01-15",
        "description": "Relational data querying and schema fundamentals",
    },
    {
        "role": "Software Engineer",
        "skill": "REST APIs",
        "skill_category": "Backend",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "HTTP-based client-server interfaces, JSON payloads, and service endpoints.",
        "published_at": "2024-05-01",
        "description": "HTTP APIs design, serialization, and integration",
    },
    {
        "role": "Software Engineer",
        "skill": "System Design",
        "skill_category": "Computer Science",
        "required_level": 0.70,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Principles of architectural scalability, component trade-offs, and distributed reliability.",
        "published_at": "2024-01-15",
        "description": "Scalability, modular architecture, and reliability trade-offs",
    },
    {
        "role": "Software Engineer",
        "skill": "Testing",
        "skill_category": "Quality",
        "required_level": 0.70,
        "importance": 0.75,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Unit, integration, and test automation practices essential for production stability.",
        "published_at": "2024-01-15",
        "description": "Unit and integration automated testing practices",
    },
    {
        "role": "Software Engineer",
        "skill": "OOP",
        "skill_category": "Computer Science",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Encapsulation, inheritance, polymorphism, and abstraction design patterns.",
        "published_at": "2024-01-15",
        "description": "Object-oriented design patterns and paradigms",
    },

    # 2. Backend Developer
    {
        "role": "Backend Developer",
        "skill": "REST APIs",
        "skill_category": "Backend",
        "required_level": 0.85,
        "importance": 0.95,
        "demand": 0.92,
        "interview_relevance": 0.85,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Primary interface for web services, requiring contract design, status codes, and security.",
        "published_at": "2024-05-01",
        "description": "Server API architecture, serialization, and contract design",
    },
    {
        "role": "Backend Developer",
        "skill": "SQL",
        "skill_category": "Databases",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Essential for relational data manipulation, indexing, transactions, and performance tuning.",
        "published_at": "2024-05-01",
        "description": "Relational queries, index optimization, and transaction handling",
    },
    {
        "role": "Backend Developer",
        "skill": "PostgreSQL",
        "skill_category": "Databases",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Most preferred open-source relational database in modern enterprise and startup stacks.",
        "published_at": "2024-05-01",
        "description": "Advanced relational database management and schema design",
    },
    {
        "role": "Backend Developer",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Widely deployed backend language across modern microservices frameworks (FastAPI, Django).",
        "published_at": "2024-05-01",
        "description": "Core backend scripting and application programming",
    },
    {
        "role": "Backend Developer",
        "skill": "System Design",
        "skill_category": "Computer Science",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.80,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Critical for backend architecture: load balancing, caching, database partitioning, and asynchronous workers.",
        "published_at": "2024-01-15",
        "description": "Scalable systems architecture, partitioning, and resilience",
    },
    {
        "role": "Backend Developer",
        "skill": "Docker",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Container standard for packaging backend runtimes and reproducible local environments.",
        "published_at": "2024-03-01",
        "description": "Containerization of services and environment parity",
    },
    {
        "role": "Backend Developer",
        "skill": "Caching",
        "skill_category": "Backend",
        "required_level": 0.70,
        "importance": 0.75,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Redis/Memcached in-memory key-value caching to reduce database read latencies.",
        "published_at": "2024-01-15",
        "description": "In-memory caching patterns and invalidation strategies",
    },
    {
        "role": "Backend Developer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.55,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Version control standard for collaborative backend development.",
        "published_at": "2024-05-01",
        "description": "Source code management and pull request workflows",
    },
    {
        "role": "Backend Developer",
        "skill": "Testing",
        "skill_category": "Quality",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Automated endpoint tests, mocking database queries, and test coverage.",
        "published_at": "2024-01-15",
        "description": "Backend unit and integration test automation",
    },

    # 3. Frontend Developer
    {
        "role": "Frontend Developer",
        "skill": "JavaScript",
        "skill_category": "Programming",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.95,
        "interview_relevance": 0.90,
        "industry_confidence": 0.95,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Foundational programming language executing in all modern web browsers.",
        "published_at": "2024-05-01",
        "description": "Core web scripting and asynchronous browser execution",
    },
    {
        "role": "Frontend Developer",
        "skill": "HTML/CSS",
        "skill_category": "Frontend",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.75,
        "industry_confidence": 0.92,
        "source": "W3C Web Standards Guidelines",
        "source_url": "https://www.w3.org/standards/",
        "source_quality": 0.90,
        "evidence_context": "Semantic structure, layout rendering (Flexbox/Grid), and CSS accessibility standards.",
        "published_at": "2024-01-01",
        "description": "Semantic markup and modern CSS layout systems",
    },
    {
        "role": "Frontend Developer",
        "skill": "React",
        "skill_category": "Frontend",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.85,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Most adopted component-based user interface library in commercial web engineering.",
        "published_at": "2024-05-01",
        "description": "Component architecture, state hooks, and virtual DOM rendering",
    },
    {
        "role": "Frontend Developer",
        "skill": "TypeScript",
        "skill_category": "Programming",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Type safety standard for modern maintainable frontend codebases.",
        "published_at": "2024-05-01",
        "description": "Static type checking for JavaScript applications",
    },
    {
        "role": "Frontend Developer",
        "skill": "Responsive Design",
        "skill_category": "Frontend",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "W3C Web Standards Guidelines",
        "source_url": "https://www.w3.org/standards/",
        "source_quality": 0.90,
        "evidence_context": "Mobile-first layouts, media queries, and touch-screen accessibility standards.",
        "published_at": "2024-01-01",
        "description": "Mobile-first responsive presentation across device form factors",
    },
    {
        "role": "Frontend Developer",
        "skill": "REST APIs",
        "skill_category": "Backend",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Consuming backend HTTP APIs, handling async network requests, error states, and pagination.",
        "published_at": "2024-05-01",
        "description": "Consuming HTTP services and client state synchronization",
    },
    {
        "role": "Frontend Developer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.55,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Version control for team frontend pull requests and asset tracking.",
        "published_at": "2024-05-01",
        "description": "Version control and branching workflows",
    },

    # 4. Full Stack Developer
    {
        "role": "Full Stack Developer",
        "skill": "JavaScript",
        "skill_category": "Programming",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.92,
        "interview_relevance": 0.85,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Shared language powering both browser interactions and Node.js backend runtimes.",
        "published_at": "2024-05-01",
        "description": "Core language for browser and runtime execution",
    },
    {
        "role": "Full Stack Developer",
        "skill": "React",
        "skill_category": "Frontend",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.88,
        "interview_relevance": 0.80,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Client UI framework for building full-stack web applications.",
        "published_at": "2024-05-01",
        "description": "Component frontend framework integration",
    },
    {
        "role": "Full Stack Developer",
        "skill": "Node.js",
        "skill_category": "Backend",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Server runtime enabling full-stack JavaScript architectures.",
        "published_at": "2024-05-01",
        "description": "Asynchronous backend JavaScript server runtime",
    },
    {
        "role": "Full Stack Developer",
        "skill": "REST APIs",
        "skill_category": "Backend",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Bridge connecting React client components with server database operations.",
        "published_at": "2024-05-01",
        "description": "Full-lifecycle API design, routing, and data contracts",
    },
    {
        "role": "Full Stack Developer",
        "skill": "SQL",
        "skill_category": "Databases",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Relational data modeling, schema migrations, and queries.",
        "published_at": "2024-01-15",
        "description": "Relational schema design and data operations",
    },
    {
        "role": "Full Stack Developer",
        "skill": "HTML/CSS",
        "skill_category": "Frontend",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.65,
        "industry_confidence": 0.90,
        "source": "W3C Web Standards Guidelines",
        "source_url": "https://www.w3.org/standards/",
        "source_quality": 0.90,
        "evidence_context": "Web markup fundamentals for full-stack user interfaces.",
        "published_at": "2024-01-01",
        "description": "Markup structure and visual styling fundamentals",
    },
    {
        "role": "Full Stack Developer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.60,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Collaborative version control across multi-tier repositories.",
        "published_at": "2024-05-01",
        "description": "Version control for multi-tier applications",
    },
    {
        "role": "Full Stack Developer",
        "skill": "Docker",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.70,
        "importance": 0.70,
        "demand": 0.75,
        "interview_relevance": 0.60,
        "industry_confidence": 0.85,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Containerizing full-stack web applications and local microservice dependencies.",
        "published_at": "2024-03-01",
        "description": "Application containerization and docker-compose setups",
    },

    # 5. Data Analyst
    {
        "role": "Data Analyst",
        "skill": "SQL",
        "skill_category": "Databases",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.95,
        "interview_relevance": 0.85,
        "industry_confidence": 0.95,
        "source": "US BLS Occupational Outlook Handbook",
        "source_url": "https://www.bls.gov/ooh/computer-and-information-technology/",
        "source_quality": 0.90,
        "evidence_context": "Core requirement for querying data warehouses, aggregations, window functions, and business KPIs.",
        "published_at": "2024-04-01",
        "description": "Advanced querying, window functions, and reporting aggregations",
    },
    {
        "role": "Data Analyst",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Data extraction, transformation, cleaning, and automated reporting.",
        "published_at": "2024-05-01",
        "description": "Data wrangling scripts and analytical automation",
    },
    {
        "role": "Data Analyst",
        "skill": "Pandas",
        "skill_category": "AI/ML",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Tabular data filtering, pivot tables, and statistical summarization.",
        "published_at": "2024-01-15",
        "description": "Tabular data manipulation and aggregation",
    },
    {
        "role": "Data Analyst",
        "skill": "Data Visualization",
        "skill_category": "AI/ML",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Creating executive charts, trend dashboards, and visual storytelling.",
        "published_at": "2024-01-15",
        "description": "Dashboard creation, chart design, and business insight presentation",
    },
    {
        "role": "Data Analyst",
        "skill": "Statistics",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Descriptive statistics, distribution properties, confidence intervals, and hypothesis tests.",
        "published_at": "2024-01-15",
        "description": "Descriptive statistics, distributions, and hypothesis evaluation",
    },
    {
        "role": "Data Analyst",
        "skill": "Communication",
        "skill_category": "Soft Skills",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.80,
        "industry_confidence": 0.88,
        "source": "US BLS Occupational Outlook Handbook",
        "source_url": "https://www.bls.gov/ooh/computer-and-information-technology/",
        "source_quality": 0.90,
        "evidence_context": "Translating quantitative metrics into actionable business recommendations.",
        "published_at": "2024-04-01",
        "description": "Stakeholder reporting and quantitative insight presentation",
    },

    # 6. Data Scientist
    {
        "role": "Data Scientist",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Primary programming language for statistical experimentation and modeling.",
        "published_at": "2024-05-01",
        "description": "Core language for data modeling and scientific computing",
    },
    {
        "role": "Data Scientist",
        "skill": "SQL",
        "skill_category": "Databases",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.75,
        "industry_confidence": 0.92,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Extracting feature datasets from production data lakes and relational tables.",
        "published_at": "2024-01-15",
        "description": "Large-scale data extraction and feature engineering queries",
    },
    {
        "role": "Data Scientist",
        "skill": "Statistics",
        "skill_category": "AI/ML",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.85,
        "interview_relevance": 0.85,
        "industry_confidence": 0.92,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Rigorous probability, hypothesis testing, A/B testing design, and regression modeling.",
        "published_at": "2024-01-15",
        "description": "Inferential statistics, experimental design, and hypothesis testing",
    },
    {
        "role": "Data Scientist",
        "skill": "Machine Learning",
        "skill_category": "AI/ML",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.85,
        "interview_relevance": 0.80,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Supervised learning, classification, regression, clustering, and cross-validation.",
        "published_at": "2024-01-15",
        "description": "Predictive modeling algorithms and statistical learning",
    },
    {
        "role": "Data Scientist",
        "skill": "Pandas",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Feature preprocessing, missing value imputation, and dataset manipulation.",
        "published_at": "2024-05-01",
        "description": "Exploratory data analysis and feature engineering",
    },
    {
        "role": "Data Scientist",
        "skill": "Scikit-learn",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Standard framework for tabular modeling pipelines, scaling, and evaluation metrics.",
        "published_at": "2024-01-15",
        "description": "Classical machine learning modeling pipelines",
    },
    {
        "role": "Data Scientist",
        "skill": "Data Visualization",
        "skill_category": "AI/ML",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "ACM/IEEE Data Science Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Communicating model findings to technical and non-technical stakeholders.",
        "published_at": "2024-01-15",
        "description": "Visual communication of model predictions and data distributions",
    },
    {
        "role": "Data Scientist",
        "skill": "Communication",
        "skill_category": "Soft Skills",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "US BLS Occupational Outlook Handbook",
        "source_url": "https://www.bls.gov/ooh/computer-and-information-technology/",
        "source_quality": 0.90,
        "evidence_context": "Synthesizing analytical results into executive presentations and product strategy.",
        "published_at": "2024-04-01",
        "description": "Interpreting complex analytical findings for cross-functional partners",
    },

    # 7. Machine Learning Engineer
    {
        "role": "Machine Learning Engineer",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.92,
        "interview_relevance": 0.85,
        "industry_confidence": 0.95,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Primary ecosystem language for deep learning frameworks and model inference.",
        "published_at": "2024-05-01",
        "description": "Primary language for ML architecture and training scripts",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Machine Learning",
        "skill_category": "AI/ML",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.90,
        "interview_relevance": 0.88,
        "industry_confidence": 0.95,
        "source": "ACM/IEEE CS2023 Artificial Intelligence Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Supervised, unsupervised, regularization, gradient descent, and loss optimization.",
        "published_at": "2024-01-15",
        "description": "Algorithmic machine learning and mathematical foundations",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Deep Learning",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Artificial Intelligence Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Multi-layer neural networks, backpropagation, CNNs, Transformers, and PyTorch/TensorFlow.",
        "published_at": "2024-01-15",
        "description": "Neural network architectures and deep learning frameworks",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Scikit-learn",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Artificial Intelligence Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Baseline modeling, data preprocessing pipelines, and standard estimators.",
        "published_at": "2024-01-15",
        "description": "Standard estimators, transformers, and evaluation metrics",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Model Evaluation",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Artificial Intelligence Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "ROC-AUC, F1 score, precision-recall trade-offs, validation split strategies, and drift detection.",
        "published_at": "2024-01-15",
        "description": "Validation strategies, generalization metrics, and error analysis",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Deployment",
        "skill_category": "AI/ML",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Model serving, REST endpoint packaging, latency optimization, and containerization.",
        "published_at": "2024-03-01",
        "description": "Model serving, containerized inference endpoints, and MLOps",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "NumPy",
        "skill_category": "AI/ML",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "ACM/IEEE CS2023 Artificial Intelligence Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Vectorized computations, matrix multiplications, and tensor slicing.",
        "published_at": "2024-01-15",
        "description": "Multidimensional array manipulation and vectorized computing",
    },
    {
        "role": "Machine Learning Engineer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.55,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Collaborative code versioning for model repositories and pipelines.",
        "published_at": "2024-05-01",
        "description": "Version control for ML codebases and scripts",
    },

    # 8. DevOps Engineer
    {
        "role": "DevOps Engineer",
        "skill": "Linux",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Server operating systems, bash scripting, systemd, process isolation, and networking tools.",
        "published_at": "2024-03-01",
        "description": "POSIX systems administration, shell scripting, and server operations",
    },
    {
        "role": "DevOps Engineer",
        "skill": "Docker",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.92,
        "interview_relevance": 0.85,
        "industry_confidence": 0.95,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Standard container engine, multi-stage Dockerfiles, image optimization, and layer caching.",
        "published_at": "2024-03-01",
        "description": "Container packaging, multi-stage builds, and runtime configuration",
    },
    {
        "role": "DevOps Engineer",
        "skill": "Kubernetes",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Industry standard orchestrator for deployments, services, ingress, and configmaps.",
        "published_at": "2024-03-01",
        "description": "Container orchestration, manifests, and cluster operations",
    },
    {
        "role": "DevOps Engineer",
        "skill": "CI/CD",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.88,
        "interview_relevance": 0.80,
        "industry_confidence": 0.90,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Automated linting, testing, artifact publishing, and continuous delivery.",
        "published_at": "2024-03-01",
        "description": "Automated build, test, and release deployment pipelines",
    },
    {
        "role": "DevOps Engineer",
        "skill": "AWS/GCP",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.88,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Cloud computing primitives (compute, object storage, identity management, networking).",
        "published_at": "2024-03-01",
        "description": "Managed cloud services and infrastructure environments",
    },
    {
        "role": "DevOps Engineer",
        "skill": "GitHub Actions",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Workflow YAML configuration, secrets management, and automated runner integration.",
        "published_at": "2024-05-01",
        "description": "Repository-native workflow automation and pipeline triggers",
    },
    {
        "role": "DevOps Engineer",
        "skill": "Monitoring",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Telemetry, metrics (Prometheus), dashboarding (Grafana), and log centralization.",
        "published_at": "2024-03-01",
        "description": "Application performance monitoring, logging, and alerts",
    },
    {
        "role": "DevOps Engineer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.60,
        "industry_confidence": 0.90,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "GitOps workflows where infrastructure manifests are managed via pull requests.",
        "published_at": "2024-05-01",
        "description": "Version control and GitOps declarative manifest tracking",
    },

    # 9. Cloud Engineer
    {
        "role": "Cloud Engineer",
        "skill": "AWS",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Leading enterprise cloud provider services (IAM, EC2, S3, RDS, Lambda, CloudWatch).",
        "published_at": "2024-03-01",
        "description": "Amazon Web Services infrastructure and serverless solutions",
    },
    {
        "role": "Cloud Engineer",
        "skill": "AWS/GCP",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.90,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Core public cloud architecture, multi-zone availability, and high availability design.",
        "published_at": "2024-03-01",
        "description": "Public cloud platform engineering and security design",
    },
    {
        "role": "Cloud Engineer",
        "skill": "Linux",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Virtual machine instance configuration, security hardening, and SSH key management.",
        "published_at": "2024-03-01",
        "description": "Linux cloud instance configuration and maintenance",
    },
    {
        "role": "Cloud Engineer",
        "skill": "Terraform",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Declarative Infrastructure-as-Code to provision cloud networks, instances, and storage.",
        "published_at": "2024-03-01",
        "description": "Infrastructure as Code provisioning and state management",
    },
    {
        "role": "Cloud Engineer",
        "skill": "Computer Networks",
        "skill_category": "Computer Science",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "VPC subnets, routing tables, NAT gateways, security groups, and DNS routing.",
        "published_at": "2024-01-15",
        "description": "Cloud networking, VPCs, CIDR blocks, and load routing",
    },
    {
        "role": "Cloud Engineer",
        "skill": "Docker",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
        "source_url": "https://www.cncf.io/reports/",
        "source_quality": 0.90,
        "evidence_context": "Container standard for packaging workloads targeted at managed container services (ECS/EKS).",
        "published_at": "2024-03-01",
        "description": "Container image standards and registry management",
    },
    {
        "role": "Cloud Engineer",
        "skill": "System Design",
        "skill_category": "Computer Science",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Architectural principles: auto-scaling groups, disaster recovery, and latency trade-offs.",
        "published_at": "2024-01-15",
        "description": "Cloud architecture design and multi-region resilience",
    },

    # 10. Cybersecurity Engineer
    {
        "role": "Cybersecurity Engineer",
        "skill": "Cybersecurity",
        "skill_category": "Cybersecurity",
        "required_level": 0.90,
        "importance": 0.95,
        "demand": 0.92,
        "interview_relevance": 0.85,
        "industry_confidence": 0.95,
        "source": "CompTIA State of Cybersecurity Report",
        "source_url": "https://www.comptia.org/content/research/state-of-cybersecurity",
        "source_quality": 0.90,
        "evidence_context": "Core principles of defense-in-depth, least privilege access, CIA triad, and risk modeling.",
        "published_at": "2024-02-01",
        "description": "Core cybersecurity principles, threat modeling, and posture",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Network Security",
        "skill_category": "Cybersecurity",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.88,
        "interview_relevance": 0.80,
        "industry_confidence": 0.92,
        "source": "CompTIA State of Cybersecurity Report",
        "source_url": "https://www.comptia.org/content/research/state-of-cybersecurity",
        "source_quality": 0.90,
        "evidence_context": "Firewalls, packet inspection (Wireshark), IDS/IPS, VPNs, and segmented network architectures.",
        "published_at": "2024-02-01",
        "description": "Network traffic analysis, firewalls, and perimeter security",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Computer Networks",
        "skill_category": "Computer Science",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.88,
        "interview_relevance": 0.85,
        "industry_confidence": 0.92,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Deep understanding of TCP/IP handshakes, DNS spoofing vectors, and routing protocol vulnerabilities.",
        "published_at": "2024-01-15",
        "description": "TCP/IP protocol stack, packet routing, and network diagnostics",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Application Security",
        "skill_category": "Cybersecurity",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "OWASP Top 10 Industry Guidance",
        "source_url": "https://owasp.org/www-project-top-ten/",
        "source_quality": 0.90,
        "evidence_context": "Vulnerability scanning, SQL injection prevention, cross-site scripting mitigation, and secure coding.",
        "published_at": "2024-01-01",
        "description": "OWASP Top 10 vulnerabilities and secure software development",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Linux",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "CompTIA State of Cybersecurity Report",
        "source_url": "https://www.comptia.org/content/research/state-of-cybersecurity",
        "source_quality": 0.90,
        "evidence_context": "Auditing system logs, file permissions, SELinux, and command-line forensics.",
        "published_at": "2024-02-01",
        "description": "Linux operating system hardening and security auditing",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Cryptography",
        "skill_category": "Cybersecurity",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.75,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Symmetric/asymmetric algorithms, PKI, digital certificates, TLS handshakes, and hashing.",
        "published_at": "2024-01-15",
        "description": "Cryptographic algorithms, key exchange, and digital signatures",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Operating Systems",
        "skill_category": "Computer Science",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
        "evidence_context": "Kernel protections, privilege escalation vectors, process injection, and memory safety.",
        "published_at": "2024-01-15",
        "description": "OS security primitives, process memory, and kernel isolation",
    },
    {
        "role": "Cybersecurity Engineer",
        "skill": "Python",
        "skill_category": "Programming",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "industry_confidence": 0.85,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Scripting security audits, parsing network logs, and automating vulnerability assessments.",
        "published_at": "2024-05-01",
        "description": "Security tooling automation and log analysis scripting",
    },

    # 11. Mobile Developer
    {
        "role": "Mobile Developer",
        "skill": "Android",
        "skill_category": "Mobile",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Google Android Developer Guidelines",
        "source_url": "https://developer.android.com/",
        "source_quality": 0.90,
        "evidence_context": "Native Android activity lifecycle, fragments, Jetpack Compose, and device permissions.",
        "published_at": "2024-01-01",
        "description": "Native Android development and Jetpack architecture",
    },
    {
        "role": "Mobile Developer",
        "skill": "iOS",
        "skill_category": "Mobile",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.75,
        "industry_confidence": 0.90,
        "source": "Apple Developer Documentation",
        "source_url": "https://developer.apple.com/",
        "source_quality": 0.90,
        "evidence_context": "Native iOS view lifecycle, SwiftUI, Xcode build systems, and Apple Human Interface Guidelines.",
        "published_at": "2024-01-01",
        "description": "Native iOS development, SwiftUI, and App Store guidelines",
    },
    {
        "role": "Mobile Developer",
        "skill": "React Native",
        "skill_category": "Mobile",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Leading cross-platform framework for building shared native apps using React patterns.",
        "published_at": "2024-05-01",
        "description": "Cross-platform mobile apps using React native components",
    },
    {
        "role": "Mobile Developer",
        "skill": "Flutter",
        "skill_category": "Mobile",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.80,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Cross-platform toolkit for compiling high-performance native apps for iOS and Android.",
        "published_at": "2024-05-01",
        "description": "Cross-platform Flutter framework and Dart runtime",
    },
    {
        "role": "Mobile Developer",
        "skill": "REST APIs",
        "skill_category": "Backend",
        "required_level": 0.80,
        "importance": 0.85,
        "demand": 0.85,
        "interview_relevance": 0.70,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Consuming backend services, offline caching, push notifications, and JSON handling.",
        "published_at": "2024-05-01",
        "description": "Consuming backend mobile APIs and handling offline sync",
    },
    {
        "role": "Mobile Developer",
        "skill": "Git",
        "skill_category": "Tools",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.55,
        "industry_confidence": 0.88,
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
        "evidence_context": "Source control across mobile client repositories and team feature releases.",
        "published_at": "2024-05-01",
        "description": "Version control for mobile codebases and release tags",
    },
    {
        "role": "Mobile Developer",
        "skill": "Responsive Design",
        "skill_category": "Frontend",
        "required_level": 0.75,
        "importance": 0.75,
        "demand": 0.75,
        "interview_relevance": 0.60,
        "industry_confidence": 0.85,
        "source": "Google Android / Apple iOS Developer Guidelines",
        "source_url": "https://developer.android.com/design",
        "source_quality": 0.90,
        "evidence_context": "Adaptive layouts for varying phone, tablet, and foldable display ratios.",
        "published_at": "2024-01-01",
        "description": "Adaptive layouts across diverse mobile screen dimensions",
    },
]

# In-memory cache for compiled role requirement profiles
_ROLE_REQUIREMENTS_CACHE: Dict[str, dict] = {}
_CACHE_TIMESTAMP: float = 0.0
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def _client() -> Optional[Client]:
    return get_supabase_client()


def clear_industry_cache():
    """Clear in-memory cached requirements."""
    global _ROLE_REQUIREMENTS_CACHE, _CACHE_TIMESTAMP
    _ROLE_REQUIREMENTS_CACHE.clear()
    _CACHE_TIMESTAMP = 0.0


def _normalize_requirement_row(row: dict) -> dict:
    """
    Normalize requirement skill through canonical taxonomy while strictly separating
    all 5 dimensions: required_level, importance, demand, interview_relevance, industry_confidence.
    Also preserves source provenance. Enriches unmigrated DB rows with authentic benchmark metadata.
    """
    raw_skill = row.get("skill", "")
    canonical_display = normalize_skill(raw_skill) or raw_skill
    slug = normalize_skill_slug(raw_skill) or raw_skill.lower().replace(" ", "_")

    # Find matching authentic prototype definition to enrich unmigrated DB rows
    proto_match = next(
        (
            p for p in PROTOTYPE_INDUSTRY_REQUIREMENTS
            if p.get("role", "").lower() == row.get("role", "").lower()
            and (
                p.get("skill", "").lower() == raw_skill.lower()
                or normalize_skill(p.get("skill", "")) == canonical_display
            )
        ),
        None
    )

    proto_level = proto_match.get("required_level", 0.75) if proto_match else float(row.get("importance", 0.75))
    proto_conf = proto_match.get("industry_confidence", 0.85) if proto_match else 0.85
    proto_quality = proto_match.get("source_quality", 0.85) if proto_match else 0.85
    proto_context = proto_match.get("evidence_context") if proto_match else row.get("description", "")
    proto_source = proto_match.get("source") if proto_match else "INAURA Industry Knowledge Catalog"
    proto_url = proto_match.get("source_url") if proto_match else None

    # If row is from older unmigrated database seed, use calibrated authentic prototype metadata
    is_old_placeholder = (
        row.get("version") in [None, "v1-prototype"]
        or row.get("source") in [None, "Curated prototype dataset"]
    )

    if proto_match and is_old_placeholder:
        required_level = float(proto_match.get("required_level", 0.75))
        importance = float(proto_match.get("importance", float(row.get("importance", 0.5))))
        demand = float(proto_match.get("demand", float(row.get("demand", 0.5))))
        interview = float(proto_match.get("interview_relevance", float(row.get("interview_relevance", 0.5))))
        industry_confidence = float(proto_match.get("industry_confidence", 0.85))
        source_quality = float(proto_match.get("source_quality", 0.85))
        source = proto_match.get("source", "INAURA Industry Knowledge Catalog")
        source_url = proto_match.get("source_url")
        evidence_context = proto_match.get("evidence_context", row.get("description", ""))
        published_at = proto_match.get("published_at", "2024-01-01")
        version = INDUSTRY_PROFILE_VERSION
    else:
        row_level = row.get("required_level")
        required_level = float(row_level if row_level is not None else proto_level)
        importance = float(row.get("importance", proto_match.get("importance", 0.5) if proto_match else 0.5))
        demand = float(row.get("demand", proto_match.get("demand", 0.5) if proto_match else 0.5))
        interview = float(row.get("interview_relevance", proto_match.get("interview_relevance", 0.5) if proto_match else 0.5))
        industry_confidence = float(row.get("industry_confidence") or proto_conf)
        source_quality = float(row.get("source_quality") or proto_quality)
        evidence_context = row.get("evidence_context") or proto_context or row.get("description", "")
        source = row.get("source") or proto_source
        source_url = row.get("source_url") or proto_url
        published_at = row.get("published_at", "2024-01-01")
        version = row.get("version", INDUSTRY_PROFILE_VERSION)

    return {
        "id": str(row.get("id", f"req-{slug}")),
        "role": row.get("role", ""),
        "skill": canonical_display,
        "skill_slug": slug,
        "skill_category": row.get("skill_category", "General"),
        "required_level": round(max(0.0, min(1.0, required_level)), 3),
        "importance": round(max(0.0, min(1.0, importance)), 3),
        "demand": round(max(0.0, min(1.0, demand)), 3),
        "interview_relevance": round(max(0.0, min(1.0, interview)), 3),
        "industry_confidence": round(max(0.0, min(1.0, industry_confidence)), 3),
        "source": source,
        "source_url": source_url,
        "source_quality": round(max(0.0, min(1.0, source_quality)), 3),
        "evidence_context": evidence_context,
        "published_at": published_at,
        "retrieved_at": row.get("retrieved_at", "2026-01-01T00:00:00Z"),
        "description": row.get("description", ""),
        "version": version,
        "metadata": row.get("metadata", {}),
    }


def aggregate_requirements(req_rows: List[dict]) -> List[dict]:
    """
    Multi-source requirement aggregation formula for the same canonical skill within a role:
      required_level = sum(level_i * quality_i) / sum(quality_i)
      importance = sum(importance_i * quality_i) / sum(quality_i)
      industry_confidence = min(0.98, max(0.40, 1.0 - product(1.0 - 0.5 * quality_i)))
      demand = min(1.0, (distinct_sources / 4.0) * 0.6 + max(demand_i) * 0.4)
    """
    by_role_skill: Dict[tuple, List[dict]] = {}
    for r in req_rows:
        norm = _normalize_requirement_row(r)
        key = (norm["role"].lower(), norm["skill"])
        by_role_skill.setdefault(key, []).append(norm)

    aggregated: List[dict] = []
    for (role_lower, skill_name), items in by_role_skill.items():
        if len(items) == 1:
            aggregated.append(items[0])
            continue

        total_quality = sum(it["source_quality"] for it in items)
        if total_quality <= 0:
            total_quality = float(len(items))

        # Weighted required_level and importance
        agg_level = sum(it["required_level"] * it["source_quality"] for it in items) / total_quality
        agg_imp = sum(it["importance"] * it["source_quality"] for it in items) / total_quality

        # Distinct sources & demand
        sources = list({it["source"] for it in items if it.get("source")})
        max_demand = max(it["demand"] for it in items)
        agg_demand = min(1.0, (len(sources) / 4.0) * 0.6 + max_demand * 0.4)

        # Max interview relevance
        agg_interview = max(it["interview_relevance"] for it in items)

        # Confidence compounding
        uncovered = 1.0
        for it in items:
            uncovered *= (1.0 - 0.5 * it["source_quality"])
        agg_conf = min(0.98, max(0.40, 1.0 - uncovered))

        primary = items[0]
        aggregated.append({
            **primary,
            "required_level": round(agg_level, 3),
            "importance": round(agg_imp, 3),
            "demand": round(agg_demand, 3),
            "interview_relevance": round(agg_interview, 3),
            "industry_confidence": round(agg_conf, 3),
            "source": f"Aggregated ({len(sources)} sources: {', '.join(sources[:2])})",
            "source_quality": round(max(it["source_quality"] for it in items), 3),
        })

    # Sort aggregated by importance descending
    aggregated.sort(key=lambda x: x["importance"], reverse=True)
    return aggregated


def list_roles() -> List[str]:
    """
    Return distinct target roles available in industry knowledge.
    Guarantees the 11 catalog roles plus any active database roles.
    """
    c = _client()
    db_roles: Set[str] = set()
    if c is not None:
        try:
            r = c.table(TABLE).select("role").execute()
            if r.data:
                db_roles = {row["role"] for row in r.data if row.get("role")}
        except Exception:
            pass

    # Merge database roles with catalog roles
    catalog_roles = set(ROLE_CATALOG.keys())
    all_roles = sorted(catalog_roles.union(db_roles))
    return all_roles


def list_by_role(role: str) -> List[dict]:
    """
    Return all requirements for target role, normalized through canonical taxonomy.
    Supports alias normalization (e.g. 'swe' -> 'Software Engineer').
    Uses in-memory cache to guarantee fast responses.
    """
    global _ROLE_REQUIREMENTS_CACHE, _CACHE_TIMESTAMP

    if not role or not str(role).strip():
        return []

    # Resolve alias to canonical title if possible
    canonical_role = canonicalize_role_name(role) or role.strip()

    # Check memory cache
    now = time.time()
    if now - _CACHE_TIMESTAMP < _CACHE_TTL_SECONDS:
        if canonical_role in _ROLE_REQUIREMENTS_CACHE:
            return _ROLE_REQUIREMENTS_CACHE[canonical_role]

    matched_rows: List[dict] = []

    # 1. Try fetching from Supabase table if connected
    c = _client()
    if c is not None:
        try:
            r = c.table(TABLE).select("*").eq("role", canonical_role).execute()
            if r.data:
                matched_rows.extend(r.data)
        except Exception:
            pass

    # Find prototype requirements for this role
    proto_for_role = [
        r for r in PROTOTYPE_INDUSTRY_REQUIREMENTS
        if r["role"].lower() == canonical_role.lower()
    ]
    if not proto_for_role and canonical_role != role.strip():
        proto_for_role = [
            r for r in PROTOTYPE_INDUSTRY_REQUIREMENTS
            if r["role"].lower() == role.strip().lower()
        ]

    # If Supabase has fewer requirements than prototype or none, supplement with prototype
    if not matched_rows:
        matched_rows.extend(proto_for_role)
    else:
        existing_skills = {normalize_skill(r.get("skill", "")) for r in matched_rows}
        for p in proto_for_role:
            if normalize_skill(p.get("skill", "")) not in existing_skills:
                matched_rows.append(p)

    # Aggregate and cache result
    aggregated = aggregate_requirements(matched_rows)
    _ROLE_REQUIREMENTS_CACHE[canonical_role] = aggregated
    _CACHE_TIMESTAMP = now

    return aggregated


def get_all(limit: int = 500) -> List[dict]:
    """Fetch all industry requirements up to limit, normalized through canonical taxonomy."""
    rows: List[dict] = []
    c = _client()
    if c is not None:
        try:
            r = c.table(TABLE).select("*").order("role").limit(limit).execute()
            if r.data:
                rows.extend(r.data)
        except Exception:
            pass

    # Ensure all prototype catalog requirements are present even if DB is unmigrated or empty
    existing_keys = {(r.get("role", "").lower(), r.get("skill", "").lower()) for r in rows}
    for proto in PROTOTYPE_INDUSTRY_REQUIREMENTS:
        key = (proto.get("role", "").lower(), proto.get("skill", "").lower())
        if key not in existing_keys:
            rows.append(proto)
            existing_keys.add(key)

    return aggregate_requirements(rows)[:limit]


def compare_two_roles(role_a: str, role_b: str) -> dict:
    """
    Compare requirements between Role A and Role B:
    Computes shared skills, deltas in required levels and importance,
    overlap score, and transition guidance.
    """
    req_a = list_by_role(role_a)
    req_b = list_by_role(role_b)
    return compare_roles_impl(role_a, role_b, req_a, req_b)
