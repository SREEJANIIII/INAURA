from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import re
from supabase import Client
from ..core.supabase import get_supabase_client


@dataclass(frozen=True)
class SkillDefinition:
    id: str  # Canonical slug: e.g., 'dsa', 'postgresql', 'react'
    canonical_name: str  # Primary name: e.g., 'Data Structures & Algorithms', 'PostgreSQL', 'React'
    display_name: str  # User-facing name
    category: str  # Category: e.g., 'Computer Science', 'Databases', 'Frontend'
    aliases: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "canonical_name": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "aliases": list(self.aliases),
            "description": self.description,
        }


# Canonical Taxonomy: Single Source of Truth
# Organized into foundational categories required for career-readiness
RAW_TAXONOMY: List[SkillDefinition] = [
    # Programming Languages
    SkillDefinition(
        id="python",
        canonical_name="Python",
        display_name="Python",
        category="Programming",
        aliases=["py", "python3", "python 3", "python programming"],
        description="General-purpose programming language for backend, scripting, and data science",
    ),
    SkillDefinition(
        id="java",
        canonical_name="Java",
        display_name="Java",
        category="Programming",
        aliases=["java8", "java11", "java17", "java 8", "java 11", "core java"],
        description="Enterprise object-oriented programming language",
    ),
    SkillDefinition(
        id="cpp",
        canonical_name="C++",
        display_name="C++",
        category="Programming",
        aliases=["c++", "cpp", "c plus plus"],
        description="Systems programming language and performance-critical development",
    ),
    SkillDefinition(
        id="c",
        canonical_name="C",
        display_name="C",
        category="Programming",
        aliases=["c language", "ansi c"],
        description="Low-level procedural systems programming language",
    ),
    SkillDefinition(
        id="csharp",
        canonical_name="C#",
        display_name="C#",
        category="Programming",
        aliases=["c#", "csharp", "c sharp", ".net", "dotnet"],
        description="Modern object-oriented programming language for .NET",
    ),
    SkillDefinition(
        id="javascript",
        canonical_name="JavaScript",
        display_name="JavaScript",
        category="Programming",
        aliases=["js", "javascript", "ecmascript", "es6", "vanilla js"],
        description="Standard language of the web for client-side and server-side execution",
    ),
    SkillDefinition(
        id="typescript",
        canonical_name="TypeScript",
        display_name="TypeScript",
        category="Programming",
        aliases=["ts", "typescript"],
        description="Typed superset of JavaScript providing static types",
    ),
    SkillDefinition(
        id="go",
        canonical_name="Go",
        display_name="Go",
        category="Programming",
        aliases=["golang", "go language"],
        description="Open source programming language for simple, fast, and reliable software",
    ),
    SkillDefinition(
        id="rust",
        canonical_name="Rust",
        display_name="Rust",
        category="Programming",
        aliases=["rustlang", "rust language"],
        description="Empowering everyone to build reliable and efficient software",
    ),

    # Computer Science Fundamentals
    SkillDefinition(
        id="dsa",
        canonical_name="Data Structures & Algorithms",
        display_name="Data Structures & Algorithms",
        category="Computer Science",
        aliases=[
            "dsa",
            "algorithms",
            "data structures",
            "data structures & algorithms",
            "data structures and algorithms",
            "algorithmic problem solving",
        ],
        description="Fundamental computational problem solving, data structures, and algorithmic complexity",
    ),
    SkillDefinition(
        id="oop",
        canonical_name="OOP",
        display_name="OOP",
        category="Computer Science",
        aliases=[
            "oop",
            "oops",
            "object oriented programming",
            "object-oriented programming",
            "object-oriented design",
        ],
        description="Object-oriented programming paradigms, encapsulation, polymorphism, inheritance",
    ),
    SkillDefinition(
        id="dbms",
        canonical_name="DBMS",
        display_name="DBMS",
        category="Computer Science",
        aliases=[
            "dbms",
            "database management",
            "database management systems",
            "rdbms",
            "relational database management",
        ],
        description="Database design, indexing, transaction management, ACID properties, normalization",
    ),
    SkillDefinition(
        id="operating_systems",
        canonical_name="Operating Systems",
        display_name="Operating Systems",
        category="Computer Science",
        aliases=[
            "operating systems",
            "operating system",
            "os fundamentals",
            "process management",
            "concurrency",
            "memory management",
        ],
        description="Processes, threads, synchronization, memory management, and file systems",
    ),
    SkillDefinition(
        id="computer_networks",
        canonical_name="Computer Networks",
        display_name="Computer Networks",
        category="Computer Science",
        aliases=[
            "computer networks",
            "computer networking",
            "networking",
            "network fundamentals",
            "tcp/ip",
            "osi model",
            "dns",
            "http/https",
        ],
        description="Network protocols, TCP/IP, OSI layers, routing, and transport protocols",
    ),
    SkillDefinition(
        id="system_design",
        canonical_name="System Design",
        display_name="System Design",
        category="Computer Science",
        aliases=[
            "system design",
            "system_design",
            "architecture",
            "software architecture",
            "distributed systems",
            "system design fundamentals",
            "scalability",
        ],
        description="Architectural patterns, scalability, reliability, caching, and distributed trade-offs",
    ),

    # Backend Development
    SkillDefinition(
        id="nodejs",
        canonical_name="Node.js",
        display_name="Node.js",
        category="Backend",
        aliases=["node", "node.js", "nodejs", "node js"],
        description="Asynchronous event-driven JavaScript runtime for server-side applications",
    ),
    SkillDefinition(
        id="express",
        canonical_name="Express",
        display_name="Express",
        category="Backend",
        aliases=["express", "express.js", "expressjs", "express js"],
        description="Fast, unopinionated, minimalist web framework for Node.js",
    ),
    SkillDefinition(
        id="spring_boot",
        canonical_name="Spring Boot",
        display_name="Spring Boot",
        category="Backend",
        aliases=["spring boot", "springboot", "spring-boot", "spring framework", "spring"],
        description="Enterprise Java framework for building microservices and web APIs",
    ),
    SkillDefinition(
        id="rest_apis",
        canonical_name="REST APIs",
        display_name="REST APIs",
        category="Backend",
        aliases=[
            "rest",
            "rest api",
            "rest apis",
            "api",
            "restful",
            "restful api",
            "restful apis",
            "fastapi",
            "fast_api",
            "flask",
            "api design",
        ],
        description="HTTP-based RESTful API architecture, endpoints, serialization, and contract design",
    ),
    SkillDefinition(
        id="caching",
        canonical_name="Caching",
        display_name="Caching",
        category="Backend",
        aliases=["caching", "cache", "memcached", "in-memory caching"],
        description="Performance optimization through caching layers and cache invalidation strategies",
    ),

    # Frontend Development
    SkillDefinition(
        id="react",
        canonical_name="React",
        display_name="React",
        category="Frontend",
        aliases=["react", "react.js", "reactjs", "react-js", "react js"],
        description="Declarative, component-based library for building user interfaces",
    ),
    SkillDefinition(
        id="nextjs",
        canonical_name="Next.js",
        display_name="Next.js",
        category="Frontend",
        aliases=["next.js", "nextjs", "next js", "next"],
        description="Full-stack React framework with SSR, SSG, and API routes",
    ),
    SkillDefinition(
        id="html",
        canonical_name="HTML",
        display_name="HTML",
        category="Frontend",
        aliases=["html", "html5", "semantic html"],
        description="HyperText Markup Language for structuring web content",
    ),
    SkillDefinition(
        id="css",
        canonical_name="CSS",
        display_name="CSS",
        category="Frontend",
        aliases=["css", "css3", "stylesheets", "tailwind", "sass", "scss"],
        description="Cascading Style Sheets for layout, presentation, and visual styling",
    ),
    SkillDefinition(
        id="html_css",
        canonical_name="HTML/CSS",
        display_name="HTML/CSS",
        category="Frontend",
        aliases=["html/css", "html css", "html & css", "html and css"],
        description="Core web markup and layout styling foundation",
    ),
    SkillDefinition(
        id="responsive_design",
        canonical_name="Responsive Design",
        display_name="Responsive Design",
        category="Frontend",
        aliases=["responsive design", "responsive", "mobile-first", "media queries"],
        description="Designing user interfaces that adapt gracefully to all screen sizes",
    ),

    # Databases
    SkillDefinition(
        id="postgresql",
        canonical_name="PostgreSQL",
        display_name="PostgreSQL",
        category="Databases",
        aliases=["postgres", "postgresql", "psql", "postgre", "postgres database"],
        description="Powerful, open-source object-relational database management system",
    ),
    SkillDefinition(
        id="mysql",
        canonical_name="MySQL",
        display_name="MySQL",
        category="Databases",
        aliases=["mysql", "my-sql"],
        description="Popular open-source relational database management system",
    ),
    SkillDefinition(
        id="mongodb",
        canonical_name="MongoDB",
        display_name="MongoDB",
        category="Databases",
        aliases=["mongodb", "mongo", "nosql mongodb"],
        description="Document-oriented NoSQL database for flexible data schemas",
    ),
    SkillDefinition(
        id="redis",
        canonical_name="Redis",
        display_name="Redis",
        category="Databases",
        aliases=["redis", "redis cache", "in-memory store"],
        description="In-memory data structure store used as a database, cache, and message broker",
    ),
    SkillDefinition(
        id="sql",
        canonical_name="SQL",
        display_name="SQL",
        category="Databases",
        aliases=["sql", "structured query language", "relational queries", "relational database"],
        description="Domain-specific language for managing relational databases and queries",
    ),

    # DevOps / Cloud / Infrastructure
    SkillDefinition(
        id="docker",
        canonical_name="Docker",
        display_name="Docker",
        category="DevOps/Cloud",
        aliases=["docker", "container", "containers", "containerization", "dockerfile", "docker-compose"],
        description="Containerization platform for packaging applications with all dependencies",
    ),
    SkillDefinition(
        id="kubernetes",
        canonical_name="Kubernetes",
        display_name="Kubernetes",
        category="DevOps/Cloud",
        aliases=["k8s", "kubernetes", "kube", "k8s orchestration"],
        description="Automated container deployment, scaling, and management platform",
    ),
    SkillDefinition(
        id="github_actions",
        canonical_name="GitHub Actions",
        display_name="GitHub Actions",
        category="DevOps/Cloud",
        aliases=["github actions", "gh actions", "github action", "gha"],
        description="CI/CD automation directly integrated with GitHub repositories",
    ),
    SkillDefinition(
        id="aws",
        canonical_name="AWS",
        display_name="AWS",
        category="DevOps/Cloud",
        aliases=["aws", "amazon web services", "ec2", "s3", "lambda"],
        description="Comprehensive cloud computing platform provided by Amazon",
    ),
    SkillDefinition(
        id="gcp",
        canonical_name="GCP",
        display_name="GCP",
        category="DevOps/Cloud",
        aliases=["gcp", "google cloud", "google cloud platform"],
        description="Suite of cloud computing services running on Google infrastructure",
    ),
    SkillDefinition(
        id="aws_gcp",
        canonical_name="AWS/GCP",
        display_name="AWS/GCP",
        category="DevOps/Cloud",
        aliases=["aws/gcp", "aws gcp", "cloud platforms", "cloud"],
        description="Public cloud infrastructure and managed service platforms",
    ),
    SkillDefinition(
        id="cicd",
        canonical_name="CI/CD",
        display_name="CI/CD",
        category="DevOps/Cloud",
        aliases=["cicd", "ci/cd", "ci cd", "continuous integration", "continuous delivery", "pipelines"],
        description="Automated testing, building, and deployment pipeline practices",
    ),
    SkillDefinition(
        id="linux",
        canonical_name="Linux",
        display_name="Linux",
        category="DevOps/Cloud",
        aliases=["linux", "unix", "bash", "shell scripting", "ubuntu"],
        description="Operating system fundamentals, shell environments, and server administration",
    ),
    SkillDefinition(
        id="monitoring",
        canonical_name="Monitoring",
        display_name="Monitoring",
        category="DevOps/Cloud",
        aliases=["monitoring", "observability", "prometheus", "grafana", "logging"],
        description="Application performance monitoring, logging, and observability",
    ),

    # AI / Machine Learning & Data Science
    SkillDefinition(
        id="machine_learning",
        canonical_name="Machine Learning",
        display_name="Machine Learning",
        category="AI/ML",
        aliases=["ml", "machine learning", "machine-learning", "predictive modeling"],
        description="Statistical learning algorithms, supervised and unsupervised modeling",
    ),
    SkillDefinition(
        id="deep_learning",
        canonical_name="Deep Learning",
        display_name="Deep Learning",
        category="AI/ML",
        aliases=["deep learning", "dl", "neural networks", "pytorch", "torch", "tensorflow", "keras"],
        description="Multi-layer neural networks, backpropagation, and representation learning",
    ),
    SkillDefinition(
        id="numpy",
        canonical_name="NumPy",
        display_name="NumPy",
        category="AI/ML",
        aliases=["numpy", "np"],
        description="Scientific computing and multidimensional array operations in Python",
    ),
    SkillDefinition(
        id="pandas",
        canonical_name="Pandas",
        display_name="Pandas",
        category="AI/ML",
        aliases=["pandas", "pd", "dataframes"],
        description="Data manipulation, wrangling, and tabular analysis in Python",
    ),
    SkillDefinition(
        id="scikit_learn",
        canonical_name="Scikit-learn",
        display_name="Scikit-learn",
        category="AI/ML",
        aliases=["scikit-learn", "sklearn", "scikit learn"],
        description="Classical machine learning tools for data mining and data analysis",
    ),
    SkillDefinition(
        id="statistics",
        canonical_name="Statistics",
        display_name="Statistics",
        category="AI/ML",
        aliases=["statistics", "stats", "probability", "statistical analysis", "hypothesis testing"],
        description="Statistical inference, probability distributions, hypothesis testing",
    ),
    SkillDefinition(
        id="data_visualization",
        canonical_name="Data Visualization",
        display_name="Data Visualization",
        category="AI/ML",
        aliases=["data viz", "data visualization", "visualization", "matplotlib", "seaborn"],
        description="Visual communication of data insights, charts, and dashboards",
    ),
    SkillDefinition(
        id="model_evaluation",
        canonical_name="Model Evaluation",
        display_name="Model Evaluation",
        category="AI/ML",
        aliases=["model evaluation", "evaluation", "metrics and validation", "cross-validation"],
        description="Evaluating model generalization, precision/recall, ROC-AUC, and loss metrics",
    ),
    SkillDefinition(
        id="deployment",
        canonical_name="Deployment",
        display_name="Deployment",
        category="AI/ML",
        aliases=["deployment", "mlops", "model serving", "deployment fundamentals"],
        description="Deploying, serving, and monitoring models and web applications in production",
    ),

    # Software Engineering Tools & Practices
    SkillDefinition(
        id="git",
        canonical_name="Git",
        display_name="Git",
        category="Tools",
        aliases=["git", "github", "version control", "vcs"],
        description="Distributed version control system for tracking source code changes",
    ),
    SkillDefinition(
        id="testing",
        canonical_name="Testing",
        display_name="Testing",
        category="Quality",
        aliases=["testing", "unit test", "unit testing", "tdd", "software testing", "test automation", "pytest", "jest"],
        description="Verification, test-driven development, integration and automated testing",
    ),
    SkillDefinition(
        id="communication",
        canonical_name="Communication",
        display_name="Communication",
        category="Soft Skills",
        aliases=["communication", "collaboration", "technical writing", "teamwork", "presentation"],
        description="Explaining technical concepts, documentation, and engineering collaboration",
    ),

    # Cybersecurity
    SkillDefinition(
        id="cybersecurity",
        canonical_name="Cybersecurity",
        display_name="Cybersecurity",
        category="Cybersecurity",
        aliases=["cybersecurity", "cyber security", "infosec", "information security", "security"],
        description="Principles of confidentiality, integrity, availability, and threat modeling",
    ),
    SkillDefinition(
        id="network_security",
        canonical_name="Network Security",
        display_name="Network Security",
        category="Cybersecurity",
        aliases=["network security", "firewalls", "vpn", "ids/ips", "packet analysis", "wireshark"],
        description="Securing network infrastructure, traffic analysis, protocols, and access control",
    ),
    SkillDefinition(
        id="application_security",
        canonical_name="Application Security",
        display_name="Application Security",
        category="Cybersecurity",
        aliases=["application security", "appsec", "owasp", "secure coding", "vulnerability assessment"],
        description="Identifying and mitigating application vulnerabilities (OWASP Top 10, penetration testing)",
    ),
    SkillDefinition(
        id="cryptography",
        canonical_name="Cryptography",
        display_name="Cryptography",
        category="Cybersecurity",
        aliases=["cryptography", "encryption", "crypto", "tls/ssl", "public key cryptography", "hashing"],
        description="Cryptographic algorithms, symmetric and asymmetric encryption, key exchange, and hashing",
    ),

    # Mobile Development
    SkillDefinition(
        id="android",
        canonical_name="Android",
        display_name="Android",
        category="Mobile",
        aliases=["android", "android dev", "android development", "android sdk"],
        description="Native Android mobile application development and lifecycle management",
    ),
    SkillDefinition(
        id="ios",
        canonical_name="iOS",
        display_name="iOS",
        category="Mobile",
        aliases=["ios", "ios dev", "ios development", "ios sdk", "uikit", "swiftui"],
        description="Native iOS mobile application development using Apple platforms",
    ),
    SkillDefinition(
        id="flutter",
        canonical_name="Flutter",
        display_name="Flutter",
        category="Mobile",
        aliases=["flutter", "dart", "flutter dev", "cross-platform flutter"],
        description="Cross-platform UI toolkit by Google for mobile, web, and desktop",
    ),
    SkillDefinition(
        id="react_native",
        canonical_name="React Native",
        display_name="React Native",
        category="Mobile",
        aliases=["react native", "react-native", "rn"],
        description="Cross-platform native mobile application framework based on React",
    ),
    SkillDefinition(
        id="kotlin",
        canonical_name="Kotlin",
        display_name="Kotlin",
        category="Programming",
        aliases=["kotlin", "kotlinlang", "kotlin programming"],
        description="Modern statically typed programming language for Android and server-side development",
    ),
    SkillDefinition(
        id="swift",
        canonical_name="Swift",
        display_name="Swift",
        category="Programming",
        aliases=["swift", "swiftlang", "swift programming"],
        description="Fast, safe, modern programming language for iOS, macOS, and beyond",
    ),

    # Additional Infrastructure
    SkillDefinition(
        id="terraform",
        canonical_name="Terraform",
        display_name="Terraform",
        category="DevOps/Cloud",
        aliases=["terraform", "iac", "infrastructure as code", "hcl"],
        description="Declarative infrastructure-as-code tool for provisioning cloud resources",
    ),
]

# Internal lookup indexes
_BY_ID: Dict[str, SkillDefinition] = {s.id: s for s in RAW_TAXONOMY}
_BY_CANONICAL_NAME_LOWER: Dict[str, SkillDefinition] = {s.canonical_name.lower(): s for s in RAW_TAXONOMY}
_BY_DISPLAY_NAME_LOWER: Dict[str, SkillDefinition] = {s.display_name.lower(): s for s in RAW_TAXONOMY}

# Map alias forms to SkillDefinition
_ALIAS_MAP: Dict[str, SkillDefinition] = {}


def _clean_key(val: str) -> str:
    """Normalize string for lookup: lowercase, strip punctuation and whitespace."""
    if not val:
        return ""
    cleaned = val.strip().lower()
    return re.sub(r"[\s\.\-_/]+", " ", cleaned).strip()


def _clean_compact_key(val: str) -> str:
    """Normalize string with no spaces: 'react.js' -> 'reactjs', 'c++' -> 'c++'."""
    if not val:
        return ""
    cleaned = val.strip().lower()
    return re.sub(r"[\s\.\-_/]+", "", cleaned)


# Initialize alias mappings
for skill in RAW_TAXONOMY:
    # Direct IDs and names
    _ALIAS_MAP[_clean_key(skill.id)] = skill
    _ALIAS_MAP[_clean_compact_key(skill.id)] = skill
    _ALIAS_MAP[_clean_key(skill.canonical_name)] = skill
    _ALIAS_MAP[_clean_compact_key(skill.canonical_name)] = skill
    _ALIAS_MAP[_clean_key(skill.display_name)] = skill
    _ALIAS_MAP[_clean_compact_key(skill.display_name)] = skill
    # All aliases
    for alias in skill.aliases:
        _ALIAS_MAP[_clean_key(alias)] = skill
        _ALIAS_MAP[_clean_compact_key(alias)] = skill

# Explicit overrides for frequent industry variations
_SPECIAL_MAPPINGS: Dict[str, str] = {
    "reactjs": "react",
    "react.js": "react",
    "react js": "react",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "dsa": "dsa",
    "rest api": "rest_apis",
    "rest apis": "rest_apis",
    "rest": "rest_apis",
    "fastapi": "rest_apis",
    "nodejs": "nodejs",
    "node.js": "nodejs",
    "k8s": "kubernetes",
    "ci/cd": "cicd",
    "cicd": "cicd",
    "gh actions": "github_actions",
    "github actions": "github_actions",
    "react native": "react_native",
    "react-native": "react_native",
    "rn": "react_native",
    "terraform": "terraform",
    "iac": "terraform",
    "appsec": "application_security",
    "infosec": "cybersecurity",
}

for raw_k, target_id in _SPECIAL_MAPPINGS.items():
    target_skill = _BY_ID.get(target_id)
    if target_skill:
        _ALIAS_MAP[_clean_key(raw_k)] = target_skill
        _ALIAS_MAP[_clean_compact_key(raw_k)] = target_skill


# Optional Supabase cache for dynamic extensions
_db_cache: Optional[Dict[str, dict]] = None


def _load_db_cache(client: Optional[Client]) -> Dict[str, dict]:
    global _db_cache
    if _db_cache is not None:
        return _db_cache
    if client is None:
        return {}
    try:
        r = client.table("skills").select("*").execute()
        data = r.data or []
        _db_cache = {row["canonical_name"]: row for row in data}
        return _db_cache
    except Exception:
        return {}


def clear_cache():
    global _db_cache
    _db_cache = None


def get_canonical_skill(raw: str, client: Optional[Client] = None) -> Optional[SkillDefinition]:
    """
    Look up the canonical SkillDefinition from any variation string.
    Returns SkillDefinition object or None if unrecognized.
    Deterministic, case-insensitive, punctuation-agnostic.
    """
    if not raw or not str(raw).strip():
        return None

    raw_str = str(raw).strip()
    key = _clean_key(raw_str)
    compact_key = _clean_compact_key(raw_str)

    # 1. In-memory built-in taxonomy alias lookup
    if key in _ALIAS_MAP:
        return _ALIAS_MAP[key]
    if compact_key in _ALIAS_MAP:
        return _ALIAS_MAP[compact_key]

    # 2. Check direct ID / canonical / display name
    if raw_str.lower() in _BY_ID:
        return _BY_ID[raw_str.lower()]
    if key in _BY_CANONICAL_NAME_LOWER:
        return _BY_CANONICAL_NAME_LOWER[key]
    if key in _BY_DISPLAY_NAME_LOWER:
        return _BY_DISPLAY_NAME_LOWER[key]

    # 3. Check DB cache if client provided
    if client is not None:
        cache = _load_db_cache(client)
        if raw_str.lower() in cache:
            row = cache[raw_str.lower()]
            return SkillDefinition(
                id=row["canonical_name"],
                canonical_name=row.get("display_name", row["canonical_name"]),
                display_name=row.get("display_name", row["canonical_name"]),
                category=row.get("category", "Other"),
                aliases=row.get("aliases", []),
                description=row.get("description", ""),
            )

    return None


def normalize_skill(raw: str, client: Optional[Client] = None) -> Optional[str]:
    """
    Map raw skill string to canonical display name.
    Examples:
      'ReactJS' -> 'React'
      'React.js' -> 'React'
      'Postgres' -> 'PostgreSQL'
      'DSA' -> 'Data Structures & Algorithms'
      'REST API' -> 'REST APIs'
      'Docker' -> 'Docker'
    Returns canonical display name, or None if no match.
    """
    skill = get_canonical_skill(raw, client)
    if skill:
        return skill.display_name
    return None


def normalize_skill_slug(raw: str, client: Optional[Client] = None) -> Optional[str]:
    """
    Map raw skill string to canonical slug ID (e.g. 'react', 'postgresql', 'dsa').
    Used for database foreign keys, system keys, and roadmap catalog lookups.
    """
    skill = get_canonical_skill(raw, client)
    if skill:
        return skill.id
    return None


def get_all_skills(client: Optional[Client] = None) -> List[dict]:
    """
    Returns all canonical skills as a list of dicts.
    Prefers in-memory single source of truth, enriched with DB records if present.
    """
    results: Dict[str, dict] = {s.id: s.to_dict() for s in RAW_TAXONOMY}
    if client is not None:
        db_data = _load_db_cache(client)
        for canon, row in db_data.items():
            if canon not in results:
                results[canon] = {
                    "id": row.get("canonical_name", canon),
                    "canonical_name": row.get("canonical_name", canon),
                    "display_name": row.get("display_name", canon.title()),
                    "category": row.get("category", "Other"),
                    "aliases": row.get("aliases", []),
                    "description": row.get("description", ""),
                }
    return list(results.values())


def extract_known_skills_from_text(text: str, client: Optional[Client] = None) -> List[SkillDefinition]:
    """
    Deterministic extraction of all canonical skills mentioned in text.
    Handles multi-word phrases ('data structures & algorithms', 'rest apis', 'spring boot')
    as well as single terms ('docker', 'python', 'react').
    Returns deduplicated list of SkillDefinition.
    """
    if not text or not text.strip():
        return []

    found: Dict[str, SkillDefinition] = {}
    cleaned_text = " " + _clean_key(text) + " "

    # Sort skills by alias length descending so longer phrases match first
    candidates: List[tuple[str, SkillDefinition]] = []
    for skill in RAW_TAXONOMY:
        # Check display name and canonical name
        candidates.append((_clean_key(skill.display_name), skill))
        candidates.append((_clean_key(skill.id), skill))
        for alias in skill.aliases:
            candidates.append((_clean_key(alias), skill))

    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for phrase, skill in candidates:
        if len(phrase) < 2:
            continue
        pattern = r"(?:\b|_)" + re.escape(phrase) + r"(?:\b|_)"
        if re.search(pattern, cleaned_text):
            if skill.id not in found:
                found[skill.id] = skill

    return list(found.values())
