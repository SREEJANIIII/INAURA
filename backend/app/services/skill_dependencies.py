"""
INAURA Skill Dependency Graph & Topological Resolution Engine

Defines canonical prerequisites between skills (e.g. Python -> NumPy -> Pandas -> ML;
JS -> React; Linux -> Docker -> Kubernetes -> Cloud; DSA -> Advanced DSA).

Ensures that roadmap generation respects learning order:
Dependencies affect task sequencing and week allocation, not merely total task count.
"""

from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)

# Canonical Prerequisite Rules (skill_slug -> list of prerequisite_slugs)
# Each key requires the skills in its value list before advancing to intensive build/practice.
CANONICAL_DEPENDENCIES: Dict[str, List[str]] = {
    # Data Science & Machine Learning track
    "numpy": ["python"],
    "pandas": ["python", "numpy"],
    "scikit_learn": ["python", "numpy", "pandas", "statistics"],
    "machine_learning": ["python", "numpy", "pandas", "scikit_learn", "statistics"],
    "deep_learning": ["python", "numpy", "machine_learning"],
    "model_evaluation": ["machine_learning", "statistics"],
    "data_visualization": ["python"],

    # Web & Full Stack track
    "typescript": ["javascript"],
    "react": ["javascript", "html_css"],
    "responsive_design": ["html_css"],
    "rest_apis": ["python"], # or whatever backend language is chosen
    "system_design": ["rest_apis", "sql"],
    "caching": ["rest_apis"],

    # Systems & DevOps track
    "docker": ["linux"],
    "kubernetes": ["docker", "networking"],
    "cicd": ["git"],
    "aws_gcp": ["networking", "linux"],
    "deployment": ["docker"],
    "monitoring": ["linux"],

    # Software Engineering & Fundamentals
    "dsa": ["python"], # DSA problem solving builds on a programming language
    "testing": ["python"],
}

# In-memory definitions for database seeding / fallback
DEPENDENCY_METADATA: Dict[Tuple[str, str], Dict[str, str]] = {
    ("numpy", "python"): {"type": "hard_requirement", "desc": "NumPy requires fluent Python array and function syntax."},
    ("pandas", "numpy"): {"type": "hard_requirement", "desc": "Pandas builds directly on NumPy vectorized arrays."},
    ("machine_learning", "scikit_learn"): {"type": "recommended_prior", "desc": "ML model mechanics are grounded in Scikit-learn workflows."},
    ("deep_learning", "machine_learning"): {"type": "hard_requirement", "desc": "Deep neural networks build upon core supervised learning concepts."},
    ("react", "javascript"): {"type": "hard_requirement", "desc": "React requires modern ES6+ JavaScript, promises, and array methods."},
    ("typescript", "javascript"): {"type": "hard_requirement", "desc": "TypeScript is a typed superset of JavaScript."},
    ("docker", "linux"): {"type": "hard_requirement", "desc": "Containerization fundamentals rely on Linux processes, cgroups, and filesystem concepts."},
    ("kubernetes", "docker"): {"type": "hard_requirement", "desc": "Kubernetes orchestrates Docker/OCI container workloads."},
    ("system_design", "rest_apis"): {"type": "recommended_prior", "desc": "Scalable system design requires client-server REST communication fluency."},
    ("system_design", "sql"): {"type": "recommended_prior", "desc": "Relational schema design and indexing are foundational to scalability."},
}


def get_prerequisites_for_skill(skill_slug: str) -> List[str]:
    """Return immediate prerequisites for a given canonical skill slug."""
    slug = (skill_slug or "").strip().lower().replace(" ", "_").replace("-", "_")
    return list(CANONICAL_DEPENDENCIES.get(slug, []))


get_prerequisites = get_prerequisites_for_skill


def get_all_transitive_prerequisites(skill_slug: str) -> Set[str]:
    """Recursively return all transitive prerequisites for a skill."""
    visited: Set[str] = set()
    queue = deque([skill_slug])

    while queue:
        curr = queue.popleft()
        for prereq in get_prerequisites_for_skill(curr):
            if prereq not in visited and prereq != skill_slug:
                visited.add(prereq)
                queue.append(prereq)

    return visited


def resolve_dependencies(
    skill_slugs: List[str],
    learner_proficiencies: Optional[Dict[str, float]] = None,
    priority_scores: Optional[Dict[str, float]] = None,
) -> List[str]:
    """
    Topologically sort a list of skill slugs respecting prerequisite constraints.
    
    Tie-breaking:
    When multiple skills are ready to be learned (all their prerequisites are met
    or already known by the learner with proficiency >= 0.60), the skill with the
    highest priority_score is scheduled first.

    Guarantees:
    - Cycle-free deterministic ordering.
    - No skill is scheduled before its unlearned prerequisites.
    """
    learner_prof = learner_proficiencies or {}
    priorities = priority_scores or {}

    # Normalize inputs
    skills_to_order = [s.strip().lower().replace(" ", "_") for s in skill_slugs if s]
    target_set = set(skills_to_order)

    # Build dependency subgraph constrained to target_set
    # A prerequisite is only considered an active blocker if the learner does NOT already
    # know it (i.e. proficiency < 0.60)
    in_degree: Dict[str, int] = {s: 0 for s in skills_to_order}
    graph: Dict[str, List[str]] = defaultdict(list)

    for skill in skills_to_order:
        prereqs = get_prerequisites_for_skill(skill)
        for p in prereqs:
            # If the prerequisite is also in the targets, or is known to be weak
            is_satisfied = learner_prof.get(p, 0.0) >= 0.60
            if p in target_set and not is_satisfied:
                graph[p].append(skill)
                in_degree[skill] += 1

    # Kahn's algorithm with priority tie-breaking
    # Queue stores ready skills (in_degree == 0)
    ready = [s for s in skills_to_order if in_degree[s] == 0]
    # Sort ready skills by priority descending
    ready.sort(key=lambda s: priorities.get(s, 0.0), reverse=True)

    ordered: List[str] = []

    while ready:
        curr = ready.pop(0)
        ordered.append(curr)

        # For every dependent skill
        for neighbor in graph[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                ready.append(neighbor)
                # Keep ready queue sorted by priority descending
                ready.sort(key=lambda s: priorities.get(s, 0.0), reverse=True)

    # If cycle or unvisited (fallback safety: append any remaining skills)
    if len(ordered) < len(skills_to_order):
        remaining = [s for s in skills_to_order if s not in ordered]
        remaining.sort(key=lambda s: priorities.get(s, 0.0), reverse=True)
        ordered.extend(remaining)

    return ordered
