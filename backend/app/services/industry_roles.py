from typing import List, Dict, Optional, Set, Any
from dataclasses import dataclass, field
import re
import math


@dataclass(frozen=True)
class RoleDefinition:
    title: str
    slug: str
    category: str
    description: str
    aliases: List[str] = field(default_factory=list)
    source_benchmarks: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "slug": self.slug,
            "category": self.category,
            "description": self.description,
            "aliases": list(self.aliases),
            "source_benchmarks": list(self.source_benchmarks),
        }


# Canonical Catalog of 11 Supported Roles
ROLE_CATALOG: Dict[str, RoleDefinition] = {
    "Software Engineer": RoleDefinition(
        title="Software Engineer",
        slug="software_engineer",
        category="Software Engineering",
        description="Generalist engineer designing, implementing, and maintaining robust software systems and algorithmic solutions.",
        aliases=[
            "software engineer",
            "swe",
            "software developer",
            "sde",
            "general software engineer",
            "software engineering",
        ],
        source_benchmarks=[
            "ACM/IEEE CS2023 Curriculum Guidelines",
            "Stack Overflow Developer Survey 2024",
            "US BLS Occupational Outlook Handbook",
        ],
    ),
    "Backend Developer": RoleDefinition(
        title="Backend Developer",
        slug="backend_developer",
        category="Software Engineering",
        description="Server-side developer responsible for business logic, REST APIs, relational databases, caching, and scalable architecture.",
        aliases=[
            "backend developer",
            "backend engineer",
            "back end developer",
            "back-end developer",
            "server engineer",
            "api engineer",
        ],
        source_benchmarks=[
            "Stack Overflow Developer Survey 2024",
            "ACM/IEEE CS2023 Backend Systems",
        ],
    ),
    "Frontend Developer": RoleDefinition(
        title="Frontend Developer",
        slug="frontend_developer",
        category="Software Engineering",
        description="Client-side engineer focused on accessible, responsive user interfaces, modern JavaScript frameworks, and design system integration.",
        aliases=[
            "frontend developer",
            "frontend engineer",
            "front end developer",
            "front-end developer",
            "ui engineer",
            "client engineer",
        ],
        source_benchmarks=[
            "Stack Overflow Developer Survey 2024",
            "W3C Web Standards & Guidelines",
        ],
    ),
    "Full Stack Developer": RoleDefinition(
        title="Full Stack Developer",
        slug="full_stack_developer",
        category="Software Engineering",
        description="Versatile engineer fluent across the complete application stack, from component UI to server APIs and database management.",
        aliases=[
            "full stack developer",
            "full stack engineer",
            "fullstack developer",
            "fullstack engineer",
            "full-stack developer",
        ],
        source_benchmarks=[
            "Stack Overflow Developer Survey 2024",
            "US BLS Occupational Outlook Handbook",
        ],
    ),
    "Data Analyst": RoleDefinition(
        title="Data Analyst",
        slug="data_analyst",
        category="Data & Analytics",
        description="Analytical specialist who extracts, transforms, queries, and visualizes structured data to drive decision-making.",
        aliases=[
            "data analyst",
            "business data analyst",
            "bi analyst",
            "analytics specialist",
            "data analytics",
        ],
        source_benchmarks=[
            "US BLS Data Scientists and Mathematical Science Occupations",
            "ACM/IEEE Data Science Curriculum Guidelines",
        ],
    ),
    "Data Scientist": RoleDefinition(
        title="Data Scientist",
        slug="data_scientist",
        category="Data & Analytics",
        description="Applied scientist combining statistical modeling, data wrangling, machine learning, and domain communication to extract insights.",
        aliases=[
            "data scientist",
            "research scientist data",
            "applied data scientist",
            "data science",
        ],
        source_benchmarks=[
            "ACM/IEEE Data Science Curriculum Guidelines",
            "Stack Overflow Developer Survey 2024",
        ],
    ),
    "Machine Learning Engineer": RoleDefinition(
        title="Machine Learning Engineer",
        slug="machine_learning_engineer",
        category="AI & Machine Learning",
        description="Engineer specialized in designing, training, evaluating, and deploying production machine learning models and neural networks.",
        aliases=[
            "machine learning engineer",
            "ml engineer",
            "mle",
            "ai/ml engineer",
            "artificial intelligence engineer",
        ],
        source_benchmarks=[
            "ACM/IEEE CS2023 Artificial Intelligence Knowledge Area",
            "Papers With Code Benchmark Trends",
        ],
    ),
    "DevOps Engineer": RoleDefinition(
        title="DevOps Engineer",
        slug="devops_engineer",
        category="Infrastructure & Security",
        description="Practitioner bridging development and operations through CI/CD pipelines, container orchestration, Linux systems, and observability.",
        aliases=[
            "devops engineer",
            "devops",
            "platform engineer",
            "sre",
            "site reliability engineer",
            "devops / cloud engineer",
        ],
        source_benchmarks=[
            "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
            "DORA State of DevOps Report",
        ],
    ),
    "Cloud Engineer": RoleDefinition(
        title="Cloud Engineer",
        slug="cloud_engineer",
        category="Infrastructure & Security",
        description="Infrastructure engineer provisioning and securing scalable cloud resources, VPC networking, infrastructure-as-code, and cloud services.",
        aliases=[
            "cloud engineer",
            "cloud solutions architect",
            "cloud infrastructure engineer",
            "aws engineer",
            "azure engineer",
        ],
        source_benchmarks=[
            "Cloud Native Computing Foundation (CNCF) Annual Survey 2024",
            "AWS / GCP Architecture Frameworks",
        ],
    ),
    "Cybersecurity Engineer": RoleDefinition(
        title="Cybersecurity Engineer",
        slug="cybersecurity_engineer",
        category="Infrastructure & Security",
        description="Security engineer protecting applications, networks, and systems via threat modeling, vulnerability mitigation, and cryptography.",
        aliases=[
            "cybersecurity engineer",
            "information security engineer",
            "security engineer",
            "cyber security analyst",
            "infosec engineer",
        ],
        source_benchmarks=[
            "OWASP Top 10 Industry Guidance",
            "CompTIA State of Cybersecurity Report",
            "NIST Cybersecurity Framework",
        ],
    ),
    "Mobile Developer": RoleDefinition(
        title="Mobile Developer",
        slug="mobile_developer",
        category="Software Engineering",
        description="Developer building responsive native and cross-platform mobile applications for iOS and Android devices.",
        aliases=[
            "mobile developer",
            "mobile engineer",
            "ios developer",
            "android developer",
            "app developer",
            "flutter developer",
            "react native developer",
        ],
        source_benchmarks=[
            "Stack Overflow Developer Survey 2024 Mobile Section",
            "Google Android / Apple iOS Developer Guidelines",
        ],
    ),
}

# Alias resolution mapping
_ROLE_ALIAS_MAP: Dict[str, str] = {}
for role_name, definition in ROLE_CATALOG.items():
    _ROLE_ALIAS_MAP[role_name.lower().strip()] = role_name
    _ROLE_ALIAS_MAP[definition.slug.lower().strip()] = role_name
    for alias in definition.aliases:
        _ROLE_ALIAS_MAP[alias.lower().strip()] = role_name


def canonicalize_role_name(input_role: str) -> Optional[str]:
    """
    Resolve role string to canonical catalog name if matched.
    Case-insensitive, punctuation-tolerant.
    Returns canonical title (e.g. 'Machine Learning Engineer') or None.
    """
    if not input_role or not str(input_role).strip():
        return None

    cleaned = input_role.strip().lower()
    if cleaned in _ROLE_ALIAS_MAP:
        return _ROLE_ALIAS_MAP[cleaned]

    # Compact search without slashes / hyphens
    compact = re.sub(r"[\s\-_/]+", " ", cleaned).strip()
    if compact in _ROLE_ALIAS_MAP:
        return _ROLE_ALIAS_MAP[compact]

    return None


def list_catalog_roles() -> List[dict]:
    """Return all 11 catalog roles with structured metadata."""
    return [role.to_dict() for role in ROLE_CATALOG.values()]


def get_role_definition(role_name: str) -> Optional[RoleDefinition]:
    """Retrieve RoleDefinition by canonical name or alias."""
    canonical = canonicalize_role_name(role_name)
    if canonical:
        return ROLE_CATALOG.get(canonical)
    return None


def compare_roles(
    role_a: str,
    role_b: str,
    requirements_a: List[dict],
    requirements_b: List[dict],
) -> dict:
    """
    Perform deep analytical comparison between two roles:
    - Shared skills and differential required levels / importance
    - Unique skills to Role A and Role B
    - Overlap score (Jaccard similarity + weighted cosine similarity)
    - Transition effort classification
    - Transferable skills and key new skills to acquire
    """
    canon_a = canonicalize_role_name(role_a) or role_a
    canon_b = canonicalize_role_name(role_b) or role_b

    map_a: Dict[str, dict] = {r.get("skill", ""): r for r in requirements_a if r.get("skill")}
    map_b: Dict[str, dict] = {r.get("skill", ""): r for r in requirements_b if r.get("skill")}

    skills_a = set(map_a.keys())
    skills_b = set(map_b.keys())

    shared_skill_names = skills_a.intersection(skills_b)
    unique_to_a_names = skills_a - skills_b
    unique_to_b_names = skills_b - skills_a

    # Jaccard overlap score
    union_skills = skills_a.union(skills_b)
    jaccard_score = len(shared_skill_names) / max(1, len(union_skills))

    # Shared skills detailed comparison
    shared_skills = []
    weighted_diff_sum = 0.0
    for name in sorted(shared_skill_names):
        req_a = map_a[name]
        req_b = map_b[name]
        level_a = float(req_a.get("required_level", req_a.get("importance", 0.5)))
        level_b = float(req_b.get("required_level", req_b.get("importance", 0.5)))
        imp_a = float(req_a.get("importance", 0.5))
        imp_b = float(req_b.get("importance", 0.5))

        diff_level = round(level_b - level_a, 2)
        diff_imp = round(imp_b - imp_a, 2)
        weighted_diff_sum += abs(diff_level) * ((imp_a + imp_b) / 2.0)

        shared_skills.append({
            "skill": name,
            "category": req_a.get("skill_category", "General"),
            "required_level_a": level_a,
            "required_level_b": level_b,
            "importance_a": imp_a,
            "importance_b": imp_b,
            "level_delta": diff_level,
            "importance_delta": diff_imp,
        })

    # Unique skills for A
    unique_skills_a = [
        {
            "skill": name,
            "category": map_a[name].get("skill_category", "General"),
            "required_level": float(map_a[name].get("required_level", 0.5)),
            "importance": float(map_a[name].get("importance", 0.5)),
        }
        for name in sorted(unique_to_a_names, key=lambda x: float(map_a[x].get("importance", 0.5)), reverse=True)
    ]

    # Unique skills for B (skills the candidate would need to pick up)
    unique_skills_b = [
        {
            "skill": name,
            "category": map_b[name].get("skill_category", "General"),
            "required_level": float(map_b[name].get("required_level", 0.5)),
            "importance": float(map_b[name].get("importance", 0.5)),
        }
        for name in sorted(unique_to_b_names, key=lambda x: float(map_b[x].get("importance", 0.5)), reverse=True)
    ]

    # Transition effort assessment
    if jaccard_score >= 0.60:
        transition_effort = "low"
        advice = f"High natural overlap between {canon_a} and {canon_b}. Transition requires minimal foundational retraining, focusing primarily on role-specific tools."
    elif jaccard_score >= 0.35:
        transition_effort = "medium"
        advice = f"Moderate overlap. Core programming and engineering fundamentals carry over directly; targeted acquisition of specialized {canon_b} domain skills is needed."
    else:
        transition_effort = "high"
        advice = f"Substantial divergence between {canon_a} and {canon_b}. Expect a comprehensive learning curve focusing on {len(unique_skills_b)} distinct domain competencies."

    # Top transferable skills (shared skills with highest combined importance)
    transferable = sorted(shared_skills, key=lambda s: s["importance_a"] + s["importance_b"], reverse=True)
    transferable_names = [s["skill"] for s in transferable[:5]]

    # Key new skills to acquire (unique to B with highest importance)
    acquire_names = [s["skill"] for s in unique_skills_b[:5]]

    return {
        "role_a": canon_a,
        "role_b": canon_b,
        "overlap_score": round(jaccard_score, 3),
        "transition_effort": transition_effort,
        "shared_skill_count": len(shared_skills),
        "unique_to_a_count": len(unique_skills_a),
        "unique_to_b_count": len(unique_skills_b),
        "shared_skills": shared_skills,
        "unique_skills_a": unique_skills_a,
        "unique_skills_b": unique_skills_b,
        "transferable_skills": transferable_names,
        "key_skills_to_acquire": acquire_names,
        "transition_advice": advice,
    }
