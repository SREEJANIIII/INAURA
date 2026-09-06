"""
Curated prototype resource catalog — Phase 4D
Not scraped, not LLM-generated.
All URLs are reputable official docs / open education / established platforms.
Marked as "curated prototype resources".
"""

# Effort heuristics (hours) — configurable, not empirically validated
EFFORT_CONFIG = {
    "learn_small": 3,      # 2-4h
    "learn_medium": 6,     # 4-8h
    "practice": 4,         # 3-6h
    "project_small": 10,   # 8-15h
    "project_medium": 18,  # 15-25h
    "assessment": 3,       # 2-4h
}

ENGINE_VERSION = "4D-v1"

# Per-skill base hours (heuristic, before gap adjustment)
# Keep values small to avoid absurdly large roadmap (total ~30-50h for 3-6 items)
SKILL_BASE_HOURS = {
    "python": 8,
    "java": 8,
    "cpp": 8,
    "dsa": 12,
    "git": 4,
    "sql": 8,
    "rest_apis": 10,
    "testing": 6,
    "system_design": 10,
    "numpy": 6,
    "pandas": 6,
    "scikit_learn": 8,
    "machine_learning": 12,
    "deep_learning": 12,
    "statistics": 6,
    "data_visualization": 6,
    "communication": 5,
    "html_css": 6,
    "javascript": 8,
    "react": 10,
    "typescript": 6,
    "responsive_design": 6,
    "docker": 8,
    "kubernetes": 10,
    "aws_gcp": 10,
    "linux": 6,
    "cicd": 6,
    "networking": 6,
    "monitoring": 6,
    "caching": 6,
    "model_evaluation": 8,
    "deployment": 10,
}

# Item type per skill (primary)
SKILL_ITEM_TYPE = {
    "python": "learn",
    "java": "learn",
    "cpp": "learn",
    "dsa": "practice",
    "git": "practice",
    "sql": "practice",
    "rest_apis": "project",
    "testing": "practice",
    "system_design": "project",
    "numpy": "practice",
    "pandas": "practice",
    "scikit_learn": "project",
    "machine_learning": "project",
    "deep_learning": "project",
    "statistics": "learn",
    "data_visualization": "project",
    "communication": "learn",
    "html_css": "practice",
    "javascript": "practice",
    "react": "project",
    "typescript": "learn",
    "responsive_design": "project",
    "docker": "project",
    "kubernetes": "project",
    "aws_gcp": "project",
    "linux": "practice",
    "cicd": "project",
    "networking": "learn",
    "monitoring": "practice",
    "caching": "project",
    "model_evaluation": "practice",
    "deployment": "project",
}

# Progression templates: what to learn/practice/build/validate
SKILL_TEMPLATES = {
    "python": {
        "learn": "Python fundamentals, data structures, functions, file I/O",
        "practice": "Solve 15 Python problems covering lists, dicts, comprehensions",
        "project": "Build a CLI tool that parses CSV and exposes results via functions",
        "validate": "Write unit tests and explain complexity of your solutions",
    },
    "dsa": {
        "learn": "Algorithmic complexity, arrays, strings, hash maps, trees, graphs",
        "practice": "Solve 20 coding problems (easy/medium) across those topics",
        "project": None,
        "validate": "Timed 90-minute problem set, analyze time/space trade-offs",
    },
    "sql": {
        "learn": "SELECT, JOINs, aggregation, indexes, normalization",
        "practice": "Query a sample database (50 exercises) with realistic datasets",
        "project": "Design and query a relational schema for an e-commerce app",
        "validate": "Explain query plans and optimize a slow query",
    },
    "rest_apis": {
        "learn": "HTTP methods, status codes, REST design, auth, pagination",
        "practice": "Call and document 5 public APIs with error handling",
        "project": "Build a production-style REST API with FastAPI/Express (CRUD, auth, tests)",
        "validate": "Write OpenAPI docs and test with edge cases",
    },
    "system_design": {
        "learn": "Scalability, load balancing, caching, database sharding, CAP",
        "practice": "Study 3 case studies (URL shortener, feed, chat)",
        "project": "Design a scalable service and document architecture decisions + trade-offs",
        "validate": "Present design and answer failure scenario questions",
    },
    "machine_learning": {
        "learn": "Supervised learning, feature engineering, bias/variance, evaluation metrics",
        "practice": "Implement and train models on 2 tabular datasets",
        "project": "Build an end-to-end prediction pipeline (cleaning → training → evaluation)",
        "validate": "Evaluate with cross-validation and explain feature importance and model choice",
    },
    "deep_learning": {
        "learn": "Neural networks, backprop, CNN/RNN basics, regularization",
        "practice": "Train a small neural net on MNIST/CIFAR with PyTorch",
        "project": "Build an image classifier and compare architectures",
        "validate": "Report accuracy, loss curves, and ablation analysis",
    },
    "docker": {
        "learn": "Containers, images, Dockerfile, volumes, networking",
        "practice": "Containerize an existing frontend/backend service",
        "project": "Deploy a multi-service app (api + db) with docker-compose",
        "validate": "Reproduce the deployment from scratch on a clean machine",
    },
    "react": {
        "learn": "Components, hooks, state, props, routing",
        "practice": "Build 3 small UI components with state and effects",
        "project": "Build a responsive dashboard consuming a REST API",
        "validate": "Test responsiveness, accessibility, and error states",
    },
    "javascript": {
        "learn": "ES6+, promises, async/await, closures, DOM",
        "practice": "Complete 20 JS exercises (array, async, DOM)",
        "project": "Build an interactive web app with API integration",
        "validate": "Review code for edge cases and performance",
    },
    "git": {
        "learn": "Commits, branching, merging, rebase, pull requests",
        "practice": "Practice branching workflow on a sample repo",
        "project": "Collaborate via PRs with meaningful commit history",
        "validate": "Resolve a merge conflict and explain strategy",
    },
    "scikit_learn": {
        "learn": "Estimators, pipelines, train-test split, hyperparameters",
        "practice": "Run pipelines on 2 datasets with GridSearchCV",
        "project": "Compare 3 models on the same dataset and justify choice",
        "validate": "Report metrics and cross-validation results",
    },
    "pandas": {
        "learn": "Series/DataFrame, cleaning, grouping, merging",
        "practice": "Wrangle 2 messy CSVs (missing values, joins)",
        "project": "Produce an analysis notebook with visualizations",
        "validate": "Explain transformations and handle edge cases",
    },
    "numpy": {
        "learn": "Arrays, broadcasting, vectorization, linear algebra basics",
        "practice": "Complete 15 NumPy exercises",
        "project": "Implement vectorized computation vs loop and benchmark",
        "validate": "Explain performance difference",
    },
    "aws_gcp": {
        "learn": "EC2/GCE, S3/GCS, IAM, VPC basics",
        "practice": "Deploy a static site and an API to cloud free tier",
        "project": "Deploy containerized service with CI/CD to cloud",
        "validate": "Document cost and security considerations",
    },
    "testing": {
        "learn": "Unit vs integration vs e2e, mocking, coverage",
        "practice": "Write tests for an existing module to reach 80% coverage",
        "project": "Add testing pipeline to your API project",
        "validate": "Run suite and explain what is not covered",
    },
}

# Fallback generic template for skills not explicitly listed
GENERIC_TEMPLATE = {
    "learn": "Core concepts and official documentation",
    "practice": "Complete guided exercises for the skill",
    "project": "Build a small practical project demonstrating the skill",
    "validate": "Review, test, and document your work",
}

# Curated resources — 1-3 per skill, reputable
RESOURCE_CATALOG = {
    "python": [
        {"title": "Python Official Tutorial", "resource_type": "documentation", "url": "https://docs.python.org/3/tutorial/", "provider": "Python Software Foundation", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Official Python tutorial — language fundamentals."},
        {"title": "Real Python — Python Basics", "resource_type": "tutorial", "url": "https://realpython.com/", "provider": "Real Python", "difficulty": "beginner", "estimated_hours": 5, "is_free": True, "description": "Practical Python tutorials and articles."},
        {"title": "Python for Everybody (Coursera)", "resource_type": "course", "url": "https://www.coursera.org/specializations/python", "provider": "University of Michigan / Coursera", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "Beginner Python course — curated prototype resource."},
    ],
    "dsa": [
        {"title": "GeeksforGeeks — Data Structures", "resource_type": "article", "url": "https://www.geeksforgeeks.org/data-structures/", "provider": "GeeksforGeeks", "difficulty": "intermediate", "estimated_hours": 5, "is_free": True, "description": "DSA concepts and implementations."},
        {"title": "LeetCode Practice", "resource_type": "practice", "url": "https://leetcode.com/problemset/", "provider": "LeetCode", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Coding practice — curated prototype."},
        {"title": "Algorithms Part I (Coursera)", "resource_type": "course", "url": "https://www.coursera.org/learn/algorithms-part1", "provider": "Princeton / Coursera", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "University algorithms course."},
    ],
    "sql": [
        {"title": "PostgreSQL Documentation", "resource_type": "documentation", "url": "https://www.postgresql.org/docs/", "provider": "PostgreSQL", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Official SQL/Postgres docs."},
        {"title": "SQLBolt — Interactive Lessons", "resource_type": "tutorial", "url": "https://sqlbolt.com/", "provider": "SQLBolt", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Interactive SQL exercises."},
        {"title": "W3Schools SQL Tutorial", "resource_type": "tutorial", "url": "https://www.w3schools.com/sql/", "provider": "W3Schools", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "SQL basics and practice."},
    ],
    "git": [
        {"title": "Pro Git Book", "resource_type": "documentation", "url": "https://git-scm.com/book/en/v2", "provider": "Git SCM", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Official Git documentation."},
        {"title": "Learn Git Branching", "resource_type": "practice", "url": "https://learngitbranching.js.org/", "provider": "Learn Git Branching", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Interactive branching practice."},
    ],
    "rest_apis": [
        {"title": "MDN — HTTP Overview", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP", "provider": "MDN Web Docs", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "HTTP and REST fundamentals."},
        {"title": "RESTful API Design Guide", "resource_type": "article", "url": "https://restfulapi.net/", "provider": "RESTfulAPI.net", "difficulty": "intermediate", "estimated_hours": 2, "is_free": True, "description": "REST principles and best practices."},
        {"title": "Swagger Docs — OpenAPI", "resource_type": "documentation", "url": "https://swagger.io/docs/specification/about/", "provider": "Swagger", "difficulty": "intermediate", "estimated_hours": 2, "is_free": True, "description": "API documentation standard."},
    ],
    "system_design": [
        {"title": "System Design Primer", "resource_type": "documentation", "url": "https://github.com/donnemartin/system-design-primer", "provider": "GitHub / Donne Martin", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Curated system design concepts and examples."},
        {"title": "Grokking System Design (preview)", "resource_type": "course", "url": "https://www.educative.io/courses/grokking-the-system-design-interview", "provider": "Educative", "difficulty": "intermediate", "estimated_hours": 8, "is_free": False, "description": "System design interview concepts — curated prototype."},
    ],
    "machine_learning": [
        {"title": "Google ML Crash Course", "resource_type": "course", "url": "https://developers.google.com/machine-learning/crash-course", "provider": "Google", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "ML foundations — curated prototype."},
        {"title": "Scikit-learn Documentation", "resource_type": "documentation", "url": "https://scikit-learn.org/stable/documentation.html", "provider": "scikit-learn", "difficulty": "intermediate", "estimated_hours": 4, "is_free": True, "description": "Official scikit-learn docs and user guide."},
        {"title": "Coursera — Machine Learning (Andrew Ng)", "resource_type": "course", "url": "https://www.coursera.org/learn/machine-learning", "provider": "Stanford / Coursera", "difficulty": "intermediate", "estimated_hours": 12, "is_free": True, "description": "Classic ML course — curated prototype."},
    ],
    "deep_learning": [
        {"title": "Deep Learning Specialization (Coursera)", "resource_type": "course", "url": "https://www.deeplearning.ai/", "provider": "DeepLearning.AI", "difficulty": "intermediate", "estimated_hours": 10, "is_free": False, "description": "Neural networks and deep learning — curated prototype."},
        {"title": "PyTorch Documentation", "resource_type": "documentation", "url": "https://pytorch.org/docs/stable/index.html", "provider": "PyTorch", "difficulty": "intermediate", "estimated_hours": 4, "is_free": True, "description": "PyTorch official docs."},
    ],
    "scikit_learn": [
        {"title": "Scikit-learn User Guide", "resource_type": "documentation", "url": "https://scikit-learn.org/stable/user_guide.html", "provider": "scikit-learn", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Scikit-learn pipelines and model selection."},
    ],
    "pandas": [
        {"title": "Pandas Documentation", "resource_type": "documentation", "url": "https://pandas.pydata.org/docs/", "provider": "NumPy / Pandas", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Official pandas docs."},
        {"title": "Kaggle Learn — Pandas", "resource_type": "tutorial", "url": "https://www.kaggle.com/learn/pandas", "provider": "Kaggle Learn", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Hands-on pandas tutorial."},
    ],
    "numpy": [
        {"title": "NumPy Documentation", "resource_type": "documentation", "url": "https://numpy.org/doc/stable/", "provider": "NumPy", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Official NumPy docs."},
    ],
    "react": [
        {"title": "React Official — Learn", "resource_type": "documentation", "url": "https://react.dev/learn", "provider": "React", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Official React tutorial."},
        {"title": "React Reference", "resource_type": "documentation", "url": "https://react.dev/reference/react", "provider": "React", "difficulty": "intermediate", "estimated_hours": 3, "is_free": True, "description": "React API reference."},
    ],
    "javascript": [
        {"title": "MDN — JavaScript Guide", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", "provider": "MDN Web Docs", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Official JavaScript guide."},
        {"title": "JavaScript.info", "resource_type": "tutorial", "url": "https://javascript.info/", "provider": "JavaScript.info", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Modern JavaScript tutorial."},
    ],
    "docker": [
        {"title": "Docker Get Started", "resource_type": "documentation", "url": "https://docs.docker.com/get-started/", "provider": "Docker", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Official Docker docs."},
        {"title": "Docker Build Guide", "resource_type": "documentation", "url": "https://docs.docker.com/build/", "provider": "Docker", "difficulty": "intermediate", "estimated_hours": 3, "is_free": True, "description": "Building images and Dockerfiles."},
    ],
    "kubernetes": [
        {"title": "Kubernetes Documentation", "resource_type": "documentation", "url": "https://kubernetes.io/docs/home/", "provider": "Kubernetes", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Official K8s docs."},
    ],
    "aws_gcp": [
        {"title": "AWS Documentation", "resource_type": "documentation", "url": "https://docs.aws.amazon.com/", "provider": "AWS", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "AWS official docs."},
        {"title": "Google Cloud Docs", "resource_type": "documentation", "url": "https://cloud.google.com/docs", "provider": "Google Cloud", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "GCP official docs."},
    ],
    "testing": [
        {"title": "Pytest Documentation", "resource_type": "documentation", "url": "https://docs.pytest.org/en/stable/", "provider": "pytest", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Python testing guide."},
        {"title": "Jest Getting Started", "resource_type": "documentation", "url": "https://jestjs.io/docs/getting-started", "provider": "Jest", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "JavaScript testing."},
    ],
    "statistics": [
        {"title": "Khan Academy — Statistics", "resource_type": "course", "url": "https://www.khanacademy.org/math/statistics-probability", "provider": "Khan Academy", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Statistics foundations."},
    ],
    "data_visualization": [
        {"title": "Matplotlib Documentation", "resource_type": "documentation", "url": "https://matplotlib.org/stable/contents.html", "provider": "Matplotlib", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "Python plotting docs."},
    ],
    "html_css": [
        {"title": "MDN — HTML Basics", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML", "provider": "MDN Web Docs", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "HTML reference."},
        {"title": "MDN — CSS Basics", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/CSS", "provider": "MDN Web Docs", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "CSS reference."},
    ],
    "model_evaluation": [
        {"title": "Scikit-learn — Model Evaluation", "resource_type": "documentation", "url": "https://scikit-learn.org/stable/modules/model_evaluation.html", "provider": "scikit-learn", "difficulty": "intermediate", "estimated_hours": 3, "is_free": True, "description": "Metrics and validation docs."},
    ],
    "deployment": [
        {"title": "MLflow Documentation", "resource_type": "documentation", "url": "https://mlflow.org/docs/latest/index.html", "provider": "MLflow", "difficulty": "intermediate", "estimated_hours": 4, "is_free": True, "description": "Model deployment and registry."},
    ],
}

# Generic fallback resources for unknown skills
GENERIC_RESOURCES = [
    {"title": "MDN Web Docs — General", "resource_type": "documentation", "url": "https://developer.mozilla.org/", "provider": "MDN Web Docs", "difficulty": "beginner", "estimated_hours": 3, "is_free": True, "description": "General web and programming docs — curated prototype fallback."},
]

def get_resources_for_skill(canonical: str):
    """Deterministic resource mapping — 1-3 resources per skill."""
    resources = RESOURCE_CATALOG.get(canonical)
    if resources:
        return resources[:3]
    # Try lowercase
    key = canonical.lower()
    if key in RESOURCE_CATALOG:
        return RESOURCE_CATALOG[key][:3]
    return GENERIC_RESOURCES[:1]

def get_template_for_skill(canonical: str):
    return SKILL_TEMPLATES.get(canonical, GENERIC_TEMPLATE)

def get_base_hours(canonical: str) -> float:
    return float(SKILL_BASE_HOURS.get(canonical, 8))

def get_item_type(canonical: str) -> str:
    return SKILL_ITEM_TYPE.get(canonical, "learn")
