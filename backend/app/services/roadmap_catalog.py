"""
Curated prototype resource catalog & task decomposition engine.
Provides authentic, reputable learning resources, realistic industry-readiness hours,
and structured multi-stage task decomposition across the canonical taxonomy.
"""

from typing import Any, Dict, List, Optional
import math

# Effort heuristics (hours) — configurable, reflecting realistic industry readiness
EFFORT_CONFIG = {
    "learn_small": 4,
    "learn_medium": 8,
    "practice": 6,
    "project_small": 12,
    "project_medium": 24,
    "assessment": 4,
}

ENGINE_VERSION = "4D-v1"

# Realistic per-skill base hours required to achieve industry readiness from zero/low baseline
SKILL_BASE_HOURS: Dict[str, float] = {
    # Core Computer Science & Foundations
    "dsa": 32.0,
    "system_design": 26.0,
    "oop": 16.0,
    "dbms": 16.0,
    "operating_systems": 18.0,
    "computer_networks": 18.0,

    # Programming Languages
    "python": 22.0,
    "java": 24.0,
    "cpp": 26.0,
    "c": 20.0,
    "csharp": 22.0,
    "javascript": 20.0,
    "typescript": 18.0,
    "go": 20.0,
    "rust": 24.0,
    "kotlin": 18.0,
    "swift": 18.0,

    # Databases & Caching
    "sql": 18.0,
    "postgresql": 18.0,
    "mysql": 16.0,
    "mongodb": 16.0,
    "redis": 14.0,
    "caching": 14.0,

    # Web & Application Architecture
    "rest_apis": 22.0,
    "react": 24.0,
    "nextjs": 18.0,
    "nodejs": 20.0,
    "express": 16.0,
    "spring_boot": 24.0,
    "html_css": 12.0,
    "html": 8.0,
    "css": 10.0,
    "responsive_design": 12.0,

    # DevOps, Cloud & Infrastructure
    "docker": 16.0,
    "kubernetes": 20.0,
    "aws_gcp": 22.0,
    "aws": 20.0,
    "gcp": 18.0,
    "linux": 14.0,
    "git": 10.0,
    "cicd": 14.0,
    "github_actions": 12.0,
    "terraform": 16.0,
    "monitoring": 12.0,
    "testing": 16.0,

    # Data Science & AI/ML
    "machine_learning": 28.0,
    "deep_learning": 30.0,
    "scikit_learn": 16.0,
    "pandas": 14.0,
    "numpy": 12.0,
    "statistics": 16.0,
    "data_visualization": 12.0,
    "model_evaluation": 14.0,
    "deployment": 16.0,

    # Cybersecurity
    "cybersecurity": 20.0,
    "network_security": 18.0,
    "application_security": 18.0,
    "cryptography": 18.0,

    # Mobile
    "android": 22.0,
    "ios": 22.0,
    "flutter": 20.0,
    "react_native": 20.0,

    # Soft Skills
    "communication": 8.0,
}

# Item type per skill
SKILL_ITEM_TYPE: Dict[str, str] = {
    "dsa": "practice",
    "system_design": "project",
    "oop": "learn",
    "dbms": "learn",
    "operating_systems": "learn",
    "computer_networks": "learn",
    "python": "learn",
    "java": "learn",
    "cpp": "learn",
    "c": "learn",
    "csharp": "learn",
    "javascript": "practice",
    "typescript": "learn",
    "go": "learn",
    "rust": "learn",
    "sql": "practice",
    "postgresql": "project",
    "mysql": "practice",
    "mongodb": "project",
    "redis": "project",
    "caching": "project",
    "rest_apis": "project",
    "react": "project",
    "nextjs": "project",
    "nodejs": "project",
    "express": "project",
    "spring_boot": "project",
    "html_css": "practice",
    "responsive_design": "project",
    "docker": "project",
    "kubernetes": "project",
    "aws_gcp": "project",
    "aws": "project",
    "gcp": "project",
    "linux": "practice",
    "git": "practice",
    "cicd": "project",
    "testing": "practice",
    "machine_learning": "project",
    "deep_learning": "project",
    "scikit_learn": "project",
    "pandas": "practice",
    "numpy": "practice",
    "statistics": "learn",
    "data_visualization": "project",
    "model_evaluation": "practice",
    "deployment": "project",
    "communication": "learn",
}

# Progression templates
SKILL_TEMPLATES: Dict[str, Dict[str, str]] = {
    "python": {
        "learn": "Python data model, OOP, closures, generator expressions, concurrency, and packaging",
        "practice": "Solve 30 algorithmic and data processing problems using idiomatic Python",
        "project": "Build an asynchronous CLI tool and background worker with SQLite/Postgres persistence",
        "validate": "Author a comprehensive Pytest suite with >85% branch coverage and benchmark performance",
    },
    "dsa": {
        "learn": "Asymptotic complexity (Big-O), arrays, hash maps, trees, graphs, heaps, and DP",
        "practice": "Solve 45 curated LeetCode Medium problems across all core algorithmic patterns",
        "project": "Implement an in-memory LRU cache and graph routing engine from scratch",
        "validate": "Complete a 90-minute timed interview problem set analyzing space/time trade-offs",
    },
    "sql": {
        "learn": "Relational algebra, multi-table JOINs, normalization (1NF-3NF), B-tree indexes, and ACID",
        "practice": "Query complex datasets with CTEs, window functions (ROW_NUMBER, DENSE_RANK), and aggregations",
        "project": "Design and migrate a production e-commerce relational schema with constraints and foreign keys",
        "validate": "Analyze query execution plans with EXPLAIN ANALYZE and optimize slow query bottlenecks",
    },
    "postgresql": {
        "learn": "PostgreSQL architecture, MVCC, connection pooling, JSONB, composite indexes, and vacuuming",
        "practice": "Write complex transactions, triggers, and stored procedures for financial ledger consistency",
        "project": "Architect a multi-tenant relational schema with row-level security (RLS) and automated migrations",
        "validate": "Benchmark read/write query latency under simulated concurrent load",
    },
    "rest_apis": {
        "learn": "HTTP semantics, idempotent methods, REST architectural constraints, JWT auth, and OpenAPI",
        "practice": "Design schema validation, pagination, query filtering, and structured error responses",
        "project": "Build a production REST API service featuring database migrations, auth middleware, and rate limiting",
        "validate": "Write automated integration tests covering token expiry, invalid input, and boundary conditions",
    },
    "system_design": {
        "learn": "Scalability, horizontal scaling, load balancing, caching tiers, database sharding, and CAP theorem",
        "practice": "Deconstruct real-world architectures (distributed URL shortener, live chat, feed generation)",
        "project": "Produce an architectural design document for a high-throughput distributed system",
        "validate": "Present architecture trade-offs and defend decisions against failure mode scenarios",
    },
    "docker": {
        "learn": "Container namespaces, cgroups, image layering, multi-stage builds, and entrypoint semantics",
        "practice": "Containerize full-stack services optimizing layer cache and minimal base image footprints",
        "project": "Deploy an interconnected multi-service application (API + Postgres + Redis) using docker-compose",
        "validate": "Verify healthcheck probes, volume persistence, non-root user execution, and zero-downtime restart",
    },
    "kubernetes": {
        "learn": "Pods, Deployments, Services, Ingress, ConfigMaps, Secrets, and rolling update strategies",
        "practice": "Draft and apply production Kubernetes manifests with resource limits and readiness probes",
        "project": "Deploy a scalable containerized service on Minikube/Kind with horizontal pod autoscaling (HPA)",
        "validate": "Simulate pod failure and verify automated recovery and traffic re-routing",
    },
    "react": {
        "learn": "Component lifecycle, state primitives (useState, useReducer), custom hooks, and React 18+ concurrency",
        "practice": "Build 6 interactive UI components handling asynchronous state, debounce, and error boundaries",
        "project": "Build a responsive web application dashboard consuming REST/GraphQL APIs with state management",
        "validate": "Write component tests with React Testing Library and verify WCAG 2.1 accessibility compliance",
    },
    "javascript": {
        "learn": "Event loop, call stack, microtask queue, closures, prototype chain, and ESNext async/await",
        "practice": "Implement functional utility libraries, debounce/throttle, and promise concurrency helpers",
        "project": "Develop an interactive data-driven browser application with zero external frameworks",
        "validate": "Audit memory leaks, performance bottlenecks, and cross-browser edge cases",
    },
    "typescript": {
        "learn": "Static type inference, generics, mapped types, conditional types, and utility types",
        "practice": "Refactor legacy JavaScript modules to strict TypeScript with zero `any` declarations",
        "project": "Author a strictly typed API client SDK with automatic type extraction from OpenAPI schemas",
        "validate": "Compile under strict mode and verify exhaustive type checking in continuous integration",
    },
    "git": {
        "learn": "Git internal object model (blobs, trees, commits, tags), HEAD mechanics, and rebase vs merge",
        "practice": "Execute feature branch workflows, interactive rebase, squashing, and conflict resolution",
        "project": "Manage multi-branch repository releases using semantic commit conventions and tags",
        "validate": "Demonstrate non-destructive recovery of detached HEAD and simulated merge conflict resolution",
    },
    "testing": {
        "learn": "Test pyramid (unit vs integration vs e2e), mock boundaries, test doubles, and mutation testing",
        "practice": "Write unit and integration tests for a complex domain service reaching >85% code coverage",
        "project": "Incorporate automated testing pipelines with coverage reporting and lint checks into CI",
        "validate": "Run mutation testing and verify test suite resistance against artificial code faults",
    },
    "operating_systems": {
        "learn": "Processes, threads, CPU scheduling, virtual memory, paging, inter-process communication (IPC), and I/O",
        "practice": "Analyze process lifecycle, thread synchronization, mutex locks, and deadlock avoidance",
        "project": "Implement a multi-threaded task pool or memory allocator simulation in Python/C++",
        "validate": "Explain kernel vs user space context switching overhead and memory page fault resolution",
    },
    "computer_networks": {
        "learn": "OSI & TCP/IP models, TCP 3-way handshake, flow control, DNS resolution, TLS/HTTPS, and HTTP/2/3",
        "practice": "Capture and inspect network packets using Wireshark/tcpdump across TCP and HTTP handshakes",
        "project": "Build a simple TCP client-server chat application with socket programming and custom protocols",
        "validate": "Diagnose network latency, packet loss, and DNS misconfiguration scenarios",
    },
    "oop": {
        "learn": "Encapsulation, inheritance, polymorphism, abstraction, and SOLID design principles",
        "practice": "Apply design patterns (Factory, Strategy, Observer, Decorator, Adapter) to refactor rigid code",
        "project": "Design an extensible object-oriented domain model for a banking or ride-sharing system",
        "validate": "Explain design pattern trade-offs and justify inheritance vs composition choices",
    },
    "dbms": {
        "learn": "Database engine internals, storage engines, buffer pools, WAL (Write-Ahead Logging), and lock modes",
        "practice": "Simulate transaction isolation anomalies (dirty read, non-repeatable read, phantom read)",
        "project": "Draft an enterprise database architecture detailing indexing, replication, and disaster recovery",
        "validate": "Demonstrate deadlock detection and verify crash recovery mechanics with WAL",
    },
    "nodejs": {
        "learn": "Node.js runtime, libuv thread pool, event-driven architecture, streams, buffers, and cluster module",
        "practice": "Build high-throughput streaming file processing and asynchronous data pipeline scripts",
        "project": "Develop a backend microservice with Express/Fastify, JWT authentication, and Postgres integration",
        "validate": "Load test the service with Autocannon/k6 and optimize event-loop latency under 5,000 req/sec",
    },
    "linux": {
        "learn": "Linux filesystem hierarchy, file permissions, shell scripting (Bash), systemd, and process management",
        "practice": "Write automation scripts for log rotation, disk monitoring, and automated backup routines",
        "project": "Configure a hardened Linux server environment with SSH keys, firewall rules, and systemd services",
        "validate": "Diagnose CPU, memory, and I/O bottlenecks using htop, iostat, vmstat, and journalctl",
    },
    "cicd": {
        "learn": "Continuous integration principles, build pipelines, automated testing, artifact staging, and CD",
        "practice": "Configure GitHub Actions workflows with matrix builds, caching, and secret management",
        "project": "Build an automated CI/CD pipeline that tests, builds Docker images, and deploys to cloud staging",
        "validate": "Simulate a failed test in a PR and verify pipeline gating blocks deployment",
    },
    "aws_gcp": {
        "learn": "Core cloud infrastructure: VPC, subnets, EC2/Compute Engine, S3/Cloud Storage, IAM, and CloudWatch",
        "practice": "Provision secure cloud networks with public/private subnets, security groups, and NAT gateways",
        "project": "Deploy a containerized application behind an Application Load Balancer with HTTPS termination",
        "validate": "Document architectural security controls, least-privilege IAM policies, and cost breakdown",
    },
    "machine_learning": {
        "learn": "Supervised/unsupervised learning, loss functions, gradient descent, bias-variance, and metrics",
        "practice": "Build end-to-end Scikit-learn pipelines with feature engineering, scaling, and GridSearchCV",
        "project": "Develop a production predictive modeling pipeline with model serialization and validation report",
        "validate": "Evaluate models using cross-validation and document feature importances and ROC-AUC curves",
    },
    "deep_learning": {
        "learn": "Neural network architectures, backpropagation, activation functions, CNNs, transformers, and PyTorch",
        "practice": "Train neural network models on benchmark datasets using PyTorch with GPU acceleration",
        "project": "Build an image classification or text sequence model with data augmentation and checkpointing",
        "validate": "Report training vs validation loss curves, precision-recall metrics, and error analysis",
    },
}

GENERIC_TEMPLATE = {
    "learn": "Core principles, official documentation, architectural patterns, and standard practices",
    "practice": "Complete progressive problem sets and exercises targeting common industry patterns",
    "project": "Build a practical production-grade project demonstrating end-to-end capability",
    "validate": "Author automated tests, benchmark performance, and complete verification checks",
}

# Curated, authoritative learning resources (official documentation, top interactive platforms, real guides)
RESOURCE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {"title": "Python Official Documentation & Tutorial", "resource_type": "documentation", "url": "https://docs.python.org/3/tutorial/", "provider": "Python Software Foundation", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "Official Python 3 language specifications, standard library, and tutorial."},
        {"title": "NeetCode — Algorithmic Problem Patterns in Python", "resource_type": "practice", "url": "https://neetcode.io/practice", "provider": "NeetCode", "difficulty": "intermediate", "estimated_hours": 14, "is_free": True, "description": "Hands-on Python implementations of core coding interview patterns: two pointers, sliding window, backtracking, and graphs."},
        {"title": "Real Python — Intermediate & Advanced Guides", "resource_type": "tutorial", "url": "https://realpython.com/", "provider": "Real Python", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Deep-dive tutorials covering OOP, decorators, generators, and async programming."},
        {"title": "Python Built-in Complexity & Data Structures Reference", "resource_type": "documentation", "url": "https://wiki.python.org/moin/TimeComplexity", "provider": "Python Wiki", "difficulty": "beginner", "estimated_hours": 4, "is_free": True, "description": "Time complexity guarantees for dict, set, list, collections.deque, and heapq in CPython."},
    ],
    "dsa": [
        {"title": "INAURA Compulsory DSA Pattern Checklist", "resource_type": "practice", "url": "https://inaura.ai/analysis/results#dsa", "provider": "INAURA", "difficulty": "intermediate", "estimated_hours": 22, "is_free": True, "description": "Interactive checklist of 71 compulsory questions categorized by pattern from NeetCode & LeetCode that directly closes your DSA gap."},
        {"title": "NeetCode 150 — Systematic Pattern Roadmap", "resource_type": "practice", "url": "https://neetcode.io/roadmap", "provider": "NeetCode", "difficulty": "intermediate", "estimated_hours": 24, "is_free": True, "description": "Structured curriculum of curated coding interview patterns across Arrays, Trees, Graphs, and DP with visual video walkthroughs."},
        {"title": "Blind 75 Curated LeetCode Problem Set", "resource_type": "practice", "url": "https://leetcode.com/discuss/general-discussion/460599/blind-75-leetcode-questions", "provider": "LeetCode / Blind 75", "difficulty": "intermediate", "estimated_hours": 20, "is_free": True, "description": "The definitive 75 questions covering every major algorithmic pattern required by top tech employers."},
        {"title": "Algorithms, Part I & II (Princeton)", "resource_type": "course", "url": "https://www.coursera.org/learn/algorithms-part1", "provider": "Princeton University", "difficulty": "advanced", "estimated_hours": 16, "is_free": True, "description": "Rigorous academic study of fundamental data structures and graph/string algorithms."},
    ],
    "sql": [
        {"title": "PostgreSQL Official Documentation", "resource_type": "documentation", "url": "https://www.postgresql.org/docs/current/", "provider": "PostgreSQL Global Development Group", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Authoritative reference for relational modeling, SQL syntax, indexes, and execution plans."},
        {"title": "SQLBolt — Interactive Lessons", "resource_type": "tutorial", "url": "https://sqlbolt.com/", "provider": "SQLBolt", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Interactive browser-based exercises covering SELECT, multi-table JOINs, and aggregates."},
        {"title": "Use The Index, Luke! — SQL Indexing Guide", "resource_type": "article", "url": "https://use-the-index-luke.com/", "provider": "Markus Winand", "difficulty": "advanced", "estimated_hours": 6, "is_free": True, "description": "The definitive guide to database performance, B-tree indexing, and query tuning."},
    ],
    "postgresql": [
        {"title": "PostgreSQL Tutorial", "resource_type": "tutorial", "url": "https://www.postgresqltutorial.com/", "provider": "PostgreSQL Tutorial", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Hands-on tutorials for PostgreSQL DDL, DML, window functions, and administration."},
        {"title": "PostgreSQL Official Docs — Server Administration", "resource_type": "documentation", "url": "https://www.postgresql.org/docs/current/admin.html", "provider": "PostgreSQL", "difficulty": "advanced", "estimated_hours": 8, "is_free": True, "description": "In-depth guide to MVCC, vacuuming, connection pooling, and replication."},
    ],
    "rest_apis": [
        {"title": "MDN Web Docs — HTTP Protocols & Semantics", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP", "provider": "Mozilla Developer Network", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Comprehensive specification of HTTP methods, status codes, headers, and caching."},
        {"title": "Microsoft REST API Guidelines", "resource_type": "documentation", "url": "https://github.com/microsoft/api-guidelines", "provider": "Microsoft", "difficulty": "advanced", "estimated_hours": 6, "is_free": True, "description": "Production engineering standards for RESTful API design, versioning, and error handling."},
        {"title": "FastAPI Official Tutorial & Documentation", "resource_type": "documentation", "url": "https://fastapi.tiangolo.com/tutorial/", "provider": "Tiangolo / FastAPI", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Modern Python framework documentation for high-performance RESTful APIs with OpenAPI."},
    ],
    "system_design": [
        {"title": "The System Design Primer", "resource_type": "documentation", "url": "https://github.com/donnemartin/system-design-primer", "provider": "Donne Martin / GitHub", "difficulty": "advanced", "estimated_hours": 16, "is_free": True, "description": "Curated collection of distributed system concepts, scalability trade-offs, and case studies."},
        {"title": "ByteByteGo — System Design Fundamentals", "resource_type": "article", "url": "https://bytebytego.com/", "provider": "Alex Xu", "difficulty": "advanced", "estimated_hours": 12, "is_free": False, "description": "Visual guides to distributed systems, message queues, database sharding, and caching."},
    ],
    "docker": [
        {"title": "Docker Official Documentation & Getting Started", "resource_type": "documentation", "url": "https://docs.docker.com/get-started/", "provider": "Docker Inc.", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "Official guide to containers, images, volumes, multi-stage Dockerfiles, and compose."},
        {"title": "Docker Labs & Hands-On Exercises", "resource_type": "practice", "url": "https://github.com/docker/labs", "provider": "Docker Community", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Practical scenarios covering multi-container orchestration, networking, and security."},
    ],
    "kubernetes": [
        {"title": "Kubernetes Official Documentation & Tasks", "resource_type": "documentation", "url": "https://kubernetes.io/docs/home/", "provider": "Cloud Native Computing Foundation", "difficulty": "advanced", "estimated_hours": 12, "is_free": True, "description": "Core concepts, architecture, and guides for pods, services, ingress, and deployments."},
        {"title": "Kubernetes the Hard Way", "resource_type": "tutorial", "url": "https://github.com/kelseyhightower/kubernetes-the-hard-way", "provider": "Kelsey Hightower", "difficulty": "advanced", "estimated_hours": 10, "is_free": True, "description": "Bootstrap Kubernetes from the ground up to understand all internal components."},
    ],
    "react": [
        {"title": "React Official Documentation — Learn React", "resource_type": "documentation", "url": "https://react.dev/learn", "provider": "Meta / React Core Team", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Modern React documentation emphasizing functional components, state, hooks, and suspense."},
        {"title": "Full Stack Open (University of Helsinki)", "resource_type": "course", "url": "https://fullstackopen.com/en/", "provider": "University of Helsinki", "difficulty": "intermediate", "estimated_hours": 16, "is_free": True, "description": "Deep-dive open course on modern single-page applications with React and REST APIs."},
    ],
    "javascript": [
        {"title": "MDN JavaScript Guide & Reference", "resource_type": "documentation", "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", "provider": "Mozilla Developer Network", "difficulty": "beginner", "estimated_hours": 10, "is_free": True, "description": "Authoritative documentation for JavaScript syntax, event loop, promises, and objects."},
        {"title": "The Modern JavaScript Tutorial", "resource_type": "tutorial", "url": "https://javascript.info/", "provider": "JavaScript.info", "difficulty": "intermediate", "estimated_hours": 12, "is_free": True, "description": "Comprehensive guide from basics to advanced topics like event loop, closures, and DOM."},
    ],
    "typescript": [
        {"title": "TypeScript Official Handbook", "resource_type": "documentation", "url": "https://www.typescriptlang.org/docs/handbook/intro.html", "provider": "Microsoft", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Official handbook covering type inference, generics, mapped types, and compiler options."},
        {"title": "Total TypeScript Tutorials", "resource_type": "tutorial", "url": "https://www.totaltypescript.com/tutorials", "provider": "Matt Pocock", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Practical interactive drills for mastering TypeScript generics and enterprise patterns."},
    ],
    "git": [
        {"title": "Pro Git Book (Official Documentation)", "resource_type": "documentation", "url": "https://git-scm.com/book/en/v2", "provider": "Git SCM / Scott Chacon", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "Complete reference manual covering Git internals, branching, rebasing, and workflows."},
        {"title": "Learn Git Branching — Interactive Visualizer", "resource_type": "practice", "url": "https://learngitbranching.js.org/", "provider": "Peter Cottle", "difficulty": "beginner", "estimated_hours": 6, "is_free": True, "description": "Interactive command-line sandbox for mastering branching, rebasing, and cherry-picking."},
    ],
    "testing": [
        {"title": "Pytest Official Documentation", "resource_type": "documentation", "url": "https://docs.pytest.org/en/stable/", "provider": "pytest-dev", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Fixtures, parametrization, mocking, test discovery, and plugin architecture."},
        {"title": "Testing JavaScript & Jest Documentation", "resource_type": "documentation", "url": "https://jestjs.io/docs/getting-started", "provider": "Jest / Meta", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Asynchronous testing, mocking, assertions, and snapshot testing standards."},
        {"title": "Martin Fowler — Practical Test Pyramid", "resource_type": "article", "url": "https://martinfowler.com/articles/practical-test-pyramid.html", "provider": "Ham Vocke / Martin Fowler", "difficulty": "advanced", "estimated_hours": 4, "is_free": True, "description": "Architectural principles for balancing unit, integration, and end-to-end tests."},
    ],
    "operating_systems": [
        {"title": "Operating Systems: Three Easy Pieces (OSTEP)", "resource_type": "course", "url": "https://pages.cs.wisc.edu/~remzi/OSTEP/", "provider": "University of Wisconsin-Madison", "difficulty": "intermediate", "estimated_hours": 14, "is_free": True, "description": "Free academic textbook covering virtualization, concurrency, and persistence."},
    ],
    "computer_networks": [
        {"title": "Computer Networking: A Top-Down Approach (Kurose & Ross)", "resource_type": "course", "url": "https://gaia.cs.umass.edu/kurose_ross/online_lectures.htm", "provider": "UMass Amherst", "difficulty": "intermediate", "estimated_hours": 14, "is_free": True, "description": "Foundational lectures on network layers, TCP/UDP sockets, DNS, and HTTP/3."},
    ],
    "oop": [
        {"title": "Refactoring Guru — Design Patterns", "resource_type": "tutorial", "url": "https://refactoring.guru/design-patterns", "provider": "Refactoring.Guru", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Visual guide to creational, structural, and behavioral design patterns and SOLID."},
    ],
    "dbms": [
        {"title": "Database Internals & CMU Database Systems", "resource_type": "course", "url": "https://15445.courses.cs.cmu.edu/", "provider": "Carnegie Mellon University", "difficulty": "advanced", "estimated_hours": 16, "is_free": True, "description": "CMU 15-445/645 course on storage models, buffer management, concurrency, and WAL."},
    ],
    "nodejs": [
        {"title": "Node.js Official Documentation & Guides", "resource_type": "documentation", "url": "https://nodejs.org/en/docs/guides", "provider": "OpenJS Foundation", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Event loop mechanics, streams, buffers, clustering, and security best practices."},
    ],
    "linux": [
        {"title": "Linux Journey — System Administration", "resource_type": "tutorial", "url": "https://linuxjourney.com/", "provider": "Linux Journey", "difficulty": "beginner", "estimated_hours": 8, "is_free": True, "description": "Step-by-step modular lessons covering Linux command line, permissions, and processes."},
    ],
    "cicd": [
        {"title": "GitHub Actions Documentation", "resource_type": "documentation", "url": "https://docs.github.com/en/actions", "provider": "GitHub", "difficulty": "intermediate", "estimated_hours": 8, "is_free": True, "description": "Workflow syntax, reusable actions, matrix builds, and continuous deployment."},
    ],
    "aws_gcp": [
        {"title": "AWS Cloud Practitioner & Architect Guides", "resource_type": "documentation", "url": "https://docs.aws.amazon.com/", "provider": "Amazon Web Services", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Official architectural guides for EC2, VPC, S3, IAM, and ECS container deployments."},
        {"title": "Google Cloud Architecture Framework", "resource_type": "documentation", "url": "https://cloud.google.com/architecture/framework", "provider": "Google Cloud", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Best practices for building reliable, secure, and high-performance cloud workloads."},
    ],
    "machine_learning": [
        {"title": "Google Machine Learning Crash Course", "resource_type": "course", "url": "https://developers.google.com/machine-learning/crash-course", "provider": "Google Developers", "difficulty": "intermediate", "estimated_hours": 12, "is_free": True, "description": "Hands-on introduction to regression, classification, neural nets, and evaluation."},
        {"title": "Scikit-Learn User Guide & API Reference", "resource_type": "documentation", "url": "https://scikit-learn.org/stable/user_guide.html", "provider": "Scikit-learn Consortium", "difficulty": "intermediate", "estimated_hours": 10, "is_free": True, "description": "Standard documentation for estimators, transformers, pipelines, and validation metrics."},
    ],
    "deep_learning": [
        {"title": "Deep Learning Specialization & Tutorials", "resource_type": "course", "url": "https://www.deeplearning.ai/", "provider": "DeepLearning.AI", "difficulty": "advanced", "estimated_hours": 16, "is_free": False, "description": "Comprehensive neural network specialization by Andrew Ng covering CNNs, RNNs, and transformers."},
        {"title": "PyTorch Official Tutorials & Documentation", "resource_type": "documentation", "url": "https://pytorch.org/tutorials/", "provider": "PyTorch / Linux Foundation", "difficulty": "intermediate", "estimated_hours": 12, "is_free": True, "description": "Tensors, autograd, neural network modules, data loaders, and model checkpoints."},
    ],
}

GENERIC_RESOURCES = [
    {"title": "DevDocs — Consolidated Developer Documentation", "resource_type": "documentation", "url": "https://devdocs.io/", "provider": "DevDocs", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Fast, organized documentation search covering modern programming languages, libraries, and tools."},
    {"title": "GitHub Awesome Curated Roadmaps & Guides", "resource_type": "documentation", "url": "https://github.com/sindresorhus/awesome", "provider": "GitHub Community", "difficulty": "intermediate", "estimated_hours": 6, "is_free": True, "description": "Curated community guides and open-source references for modern software engineering."},
]


def _normalize_key(canonical: str) -> str:
    if not canonical:
        return ""
    try:
        from .skill_taxonomy import normalize_skill_slug
        slug = normalize_skill_slug(canonical)
        if slug:
            return slug
    except Exception:
        pass
    return canonical.lower().strip().replace(" ", "_").replace(".", "").replace("-", "_")


def get_resources_for_skill(canonical: str) -> List[Dict[str, Any]]:
    """Deterministic resource mapping — 2 to 3 curated authoritative resources per skill."""
    key = _normalize_key(canonical)
    resources = RESOURCE_CATALOG.get(key)
    if resources:
        return resources[:3]
    if key in ("postgresql", "mysql") and "sql" in RESOURCE_CATALOG:
        return (RESOURCE_CATALOG.get(key) or RESOURCE_CATALOG["sql"])[:3]
    if key in ("aws", "gcp") and "aws_gcp" in RESOURCE_CATALOG:
        return RESOURCE_CATALOG["aws_gcp"][:3]
    return GENERIC_RESOURCES[:2]


def get_template_for_skill(canonical: str) -> Dict[str, str]:
    key = _normalize_key(canonical)
    return SKILL_TEMPLATES.get(key, GENERIC_TEMPLATE)


def get_base_hours(canonical: str) -> float:
    key = _normalize_key(canonical)
    return float(SKILL_BASE_HOURS.get(key, 16.0))


def get_item_type(canonical: str) -> str:
    key = _normalize_key(canonical)
    return SKILL_ITEM_TYPE.get(key, "learn")


# Multi-stage granular task decomposition blocks (6 to 8 actionable, bite-sized tasks per skill)
SKILL_DECOMPOSED_BLOCKS: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {"stage": "learn", "title": "Python Syntax, Data Model & Control Flow", "desc": "Master core syntax, dynamic typing semantics, scope rules (LEGB), and functions.", "val_method": "quiz"},
        {"stage": "learn", "title": "Advanced Python: Comprehensions, Closures & Decorators", "desc": "Deep dive into generator expressions, custom decorators, context managers, and dunder methods.", "val_method": "quiz"},
        {"stage": "practice", "title": "Algorithmic & Data Processing Problem Set", "desc": "Solve 20 exercises focusing on dictionary lookups, set operations, string manipulation, and list comprehensions.", "val_method": "practical_test"},
        {"stage": "practice", "title": "File I/O, Serialization & Exception Handling Drills", "desc": "Process structured JSON/CSV data streams, handle malformed input gracefully, and log execution details.", "val_method": "practical_test"},
        {"stage": "build", "title": "Architect & Model a Modular Data Processing CLI Tool", "desc": "Structure a multi-file Python application with argparse/click, configuration management, and clean boundaries.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Implement Background Data Workers & SQLite Persistence", "desc": "Write persistent storage layers with SQLite/Postgres and implement thread-safe batch processing routines.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Pytest Test Suite & Branch Coverage Verification", "desc": "Author comprehensive unit and parameterized integration tests achieving >85% code coverage.", "val_method": "code_submission"},
        {"stage": "validate", "title": "Code Complexity & PEP 8 Quality Defense", "desc": "Audit time/space complexity, run Flake8/Black linters, and document error-handling strategies.", "val_method": "self_check"},
    ],
    "sql": [
        {"stage": "learn", "title": "Relational Modeling, Constraints & Normalization (1NF-3NF)", "desc": "Understand relational schema design, primary/foreign keys, uniqueness constraints, and eliminating redundancy.", "val_method": "quiz"},
        {"stage": "learn", "title": "B-Tree Indexes, ACID Guarantees & Transaction Isolation", "desc": "Learn how database engines index data, maintain write-ahead logs, and enforce isolation levels.", "val_method": "quiz"},
        {"stage": "practice", "title": "Complex Multi-Table JOINs & Aggregation Challenges", "desc": "Complete 25 exercises covering INNER/LEFT/FULL OUTER JOINs, GROUP BY, HAVING, and subqueries.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Advanced Analytics: Window Functions & Common Table Expressions", "desc": "Implement ROW_NUMBER, RANK, DENSE_RANK, moving averages, and recursive CTE queries on real data.", "val_method": "practical_test"},
        {"stage": "build", "title": "Design & Migrate an Enterprise Relational Schema", "desc": "Author DDL migration scripts for an e-commerce or SaaS platform with indexes and integrity checks.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Implement Performance-Tuned Business Reporting Queries", "desc": "Draft complex queries answering business questions, utilizing indexes and avoiding full table scans.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Query Plan Optimization with EXPLAIN ANALYZE", "desc": "Inspect query cost and execution times before and after indexing to prove measurable performance gains.", "val_method": "code_submission"},
    ],
    "dsa": [
        {"stage": "learn", "title": "Big-O Asymptotic Complexity & Algorithmic Patterns", "desc": "Analyze worst-case, average-case, and amortized time/space complexity across arrays, lists, maps, and recursion trees.", "val_method": "quiz"},
        {"stage": "learn", "title": "Hash Tables, Linked Lists & Binary Search Trees", "desc": "Master hash collisions, fast & slow pointers, linked list in-place reversal, and binary search tree invariants.", "val_method": "quiz"},
        {"stage": "learn", "title": "Graph Traversals (BFS/DFS), Heaps & Dynamic Programming", "desc": "Master queue-based BFS, DFS topological sorting, priority queues, and memoization vs tabulation state transitions.", "val_method": "quiz"},
        {"stage": "practice", "title": "NeetCode Pattern Pillar: Two Pointers & Sliding Window", "desc": "Solve compulsory pattern questions (Two Sum II, 3Sum, Container With Most Water, Minimum Window Substring) on NeetCode/LeetCode.", "val_method": "practical_test"},
        {"stage": "practice", "title": "NeetCode Pattern Pillar: Trees, Graphs & Backtracking", "desc": "Solve compulsory questions (Level Order Traversal, Lowest Common Ancestor, Course Schedule, Number of Islands, Subsets).", "val_method": "practical_test"},
        {"stage": "practice", "title": "NeetCode Pattern Pillar: Dynamic Programming & Greedy", "desc": "Master 1-D & 2-D DP (Climbing Stairs, Coin Change, Longest Increasing Subsequence, Longest Common Subsequence, Kadane's).", "val_method": "practical_test"},
        {"stage": "build", "title": "Implement an In-Memory LRU Cache & Graph Router from Scratch", "desc": "Write a clean object-oriented implementation of an LRU cache (hash map + doubly linked list) and topological build router.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Complete INAURA Compulsory DSA Pattern Checklist", "desc": "Tick off compulsory questions across all 15 industry patterns to systematically verify capability and close your DSA gap.", "val_method": "quiz"},
        {"stage": "validate", "title": "90-Minute Timed Algorithmic Technical Interview", "desc": "Complete a timed problem set simulating technical interview constraints and defend space/time complexity trade-offs.", "val_method": "code_submission"},
    ],
    "rest_apis": [
        {"stage": "learn", "title": "HTTP Semantics, Resource Modeling & REST Constraints", "desc": "Understand idempotent methods (GET, PUT, DELETE), safe methods, status codes, and URI hierarchy.", "val_method": "quiz"},
        {"stage": "learn", "title": "Authentication Middleware, JWT Tokens & Rate Limiting", "desc": "Study stateless authentication, bearer token verification, token expiration, and request throttling.", "val_method": "quiz"},
        {"stage": "practice", "title": "Request Validation, Pagination & Structured Errors", "desc": "Implement robust schema parsing (Pydantic/Zod), cursor/offset pagination, and unified error responses.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Consuming & Integrating External Third-Party APIs", "desc": "Build resilient client adapters with retry backoff, timeout handling, and structured mock interfaces.", "val_method": "practical_test"},
        {"stage": "build", "title": "Build a Production-Ready CRUD Service with Persistence", "desc": "Develop a backend API service in FastAPI or Express featuring database migrations, ORM, and auth middleware.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Implement Role-Based Access Control (RBAC) & OpenAPI Specs", "desc": "Secure endpoints by user roles, generate interactive OpenAPI documentation, and configure CORS policies.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Automated End-to-End API Test Suite", "desc": "Author integration tests verifying invalid tokens, schema boundary violations, and concurrent writes.", "val_method": "code_submission"},
    ],
    "system_design": [
        {"stage": "learn", "title": "Scalability Fundamentals, Load Balancing & Horizontal Growth", "desc": "Master vertical vs horizontal scaling, reverse proxies, round-robin vs least-connections, and stateless servers.", "val_method": "quiz"},
        {"stage": "learn", "title": "Database Scaling: Replication, Sharding & CAP Theorem", "desc": "Understand primary-replica setups, read replicas, consistent hashing, partition tolerance, and eventual consistency.", "val_method": "quiz"},
        {"stage": "learn", "title": "Caching Tiers & Asynchronous Message Queues", "desc": "Study write-through vs write-back caching, cache invalidation, Redis, Kafka/RabbitMQ, and decoupled workers.", "val_method": "quiz"},
        {"stage": "practice", "title": "Deconstruct Real-World Architecture Case Studies", "desc": "Analyze architectures for a distributed URL shortener, photo-sharing feed, and high-concurrency rate limiter.", "val_method": "practical_test"},
        {"stage": "build", "title": "Draft Comprehensive System Architecture Document", "desc": "Produce complete architectural schematics, data flow diagrams, schema designs, and latency/QPS estimations.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Design Component Resiliency & Disaster Recovery Plan", "desc": "Detail circuit breaker patterns, bulkhead isolation, retry jitter, and data backup replication strategies.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "System Design Architecture Presentation & Defense", "desc": "Present design trade-offs, answer simulated failure scenarios (e.g. primary DB failure), and defend bottlenecks.", "val_method": "quiz"},
    ],
    "docker": [
        {"stage": "learn", "title": "Container Architecture, Namespaces, Cgroups & Images", "desc": "Learn how containers isolate processes, image layer caching mechanics, and container lifecycle.", "val_method": "quiz"},
        {"stage": "learn", "title": "Dockerfile Directives, Security & Multi-Stage Builds", "desc": "Master multi-stage Dockerfiles, minimal base images (Alpine/Distroless), non-root execution, and ENV configurations.", "val_method": "quiz"},
        {"stage": "practice", "title": "Containerize Full-Stack Applications with Layer Caching", "desc": "Write optimized Dockerfiles for backend and frontend apps, minimizing image size from 1GB+ down to <150MB.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Volume Mounting, Port Forwarding & Container Networking", "desc": "Configure named volumes for persistent data, bridge networks, and DNS resolution between containers.", "val_method": "practical_test"},
        {"stage": "build", "title": "Deploy Multi-Service Stack with Docker Compose", "desc": "Orchestrate an interconnected environment (API, Postgres database, Redis cache, and frontend) using compose.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Configure Healthchecks, Restart Policies & Secret Isolation", "desc": "Implement robust health check endpoints, graceful shutdown signals (SIGTERM), and `.env` secret protection.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Zero-Downtime Rebuild & Clean Deployment Verification", "desc": "Verify reproducible builds on a fresh machine, automated container restarts upon crash, and data persistence.", "val_method": "code_submission"},
    ],
    "react": [
        {"stage": "learn", "title": "Component Tree, Virtual DOM & JSX Rendering Rules", "desc": "Understand declarative UI, unidirectional data flow, reconciliation algorithm, and pure component rules.", "val_method": "quiz"},
        {"stage": "learn", "title": "State Primitives & Hook Lifecycles (useState, useEffect, useMemo)", "desc": "Master hook dependencies, closure traps, derived state, custom hooks, and avoiding unnecessary re-renders.", "val_method": "quiz"},
        {"stage": "practice", "title": "Interactive Controlled Forms & Async State Management", "desc": "Build form validation interfaces, debounced search inputs, and resilient async data-fetching hooks.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Context API, Reducers & Global State Architecture", "desc": "Implement multi-page app state with useReducer and Context, optimizing component subscription boundaries.", "val_method": "practical_test"},
        {"stage": "build", "title": "Develop a Production Web Application Dashboard", "desc": "Build a responsive multi-view web dashboard consuming REST APIs with routing, loading skeletons, and error boundaries.", "val_method": "repo_inspection"},
        {"stage": "build", "title": "Implement Filtering, Sorting & Persistent Preferences", "desc": "Add client-side pagination, complex search filters, dark/light theme switching, and local storage sync.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Component Testing with React Testing Library", "desc": "Author tests verifying user interactions, form submissions, accessibility roles, and API error states.", "val_method": "code_submission"},
    ],
    "testing": [
        {"stage": "learn", "title": "Testing Philosophy, Test Pyramid & Unit Boundaries", "desc": "Understand isolation vs integration, AAA (Arrange-Act-Assert) pattern, and test determinism.", "val_method": "quiz"},
        {"stage": "learn", "title": "Test Doubles: Mocks, Stubs, Spies & Dependency Injection", "desc": "Learn when to mock external network/database calls and when to verify state vs behavior.", "val_method": "quiz"},
        {"stage": "practice", "title": "Authoring Unit Tests for Complex Business Rules", "desc": "Write parameterized test suites covering edge cases, null boundaries, and error exceptions.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Database & Integration Testing with Ephemeral Environments", "desc": "Set up test containers / SQLite in-memory databases for true integration testing without data pollution.", "val_method": "practical_test"},
        {"stage": "build", "title": "Implement Complete Automated Test Suite with Coverage", "desc": "Equip an existing application with comprehensive unit, integration, and contract tests reaching >85% coverage.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Mutation Testing & CI Pipeline Quality Gates", "desc": "Run mutation testing to identify weak assertions, configure CI test runners, and enforce coverage gates.", "val_method": "code_submission"},
    ],
    "git": [
        {"stage": "learn", "title": "Git Object Model & Internal Reference Mechanics", "desc": "Understand blobs, trees, commits, annotated tags, HEAD pointers, and index staging area.", "val_method": "quiz"},
        {"stage": "learn", "title": "Branching Strategies: GitFlow, Trunk-Based & Rebasing", "desc": "Master rebase vs merge semantics, interactive rebase, squashing, and clean linear commit histories.", "val_method": "quiz"},
        {"stage": "practice", "title": "Simulated Merge Conflict Resolution Challenges", "desc": "Practice creating intentional branch divergence, 3-way conflict resolution, and aborting failed merges.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Stashing, Cherry-Picking & Reflog Emergency Recovery", "desc": "Rescue lost commits with `git reflog`, cherry-pick hotfixes across branches, and manage dirty working trees.", "val_method": "practical_test"},
        {"stage": "build", "title": "Collaborative Pull Request Workflow & Semantic Versioning", "desc": "Configure branch protection rules, write conventional commit messages, and author structured pull requests.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Repository Cleanliness & Conflict-Free Release Verification", "desc": "Produce a verified git log demonstrating clean commit hygiene, signed commits, and release tags.", "val_method": "self_check"},
    ],
    "oop": [
        {"stage": "learn", "title": "OOP Core Foundations: Encapsulation & Polymorphism", "desc": "Master data hiding, class vs object identity, dynamic dispatch, and interface contracts.", "val_method": "quiz"},
        {"stage": "learn", "title": "SOLID Principles & Composition over Inheritance", "desc": "Deep dive into Single Responsibility, Open-Closed, Liskov Substitution, and Dependency Inversion.", "val_method": "quiz"},
        {"stage": "practice", "title": "Refactoring Procedural Code into Object-Oriented Models", "desc": "Refactor monolithic functions into cohesive classes utilizing polymorphism instead of switch statements.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Implementing Gang of Four (GoF) Design Patterns", "desc": "Implement Factory, Strategy, Observer, and Decorator patterns in realistic business scenarios.", "val_method": "practical_test"},
        {"stage": "build", "title": "Design & Build an Extensible Domain Model Architecture", "desc": "Build a modular object-oriented domain system (e.g. payment processing, order fulfillment) with clean interfaces.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Design Pattern Justification & Architecture Review", "desc": "Defend design decisions, explain trade-offs of chosen patterns, and verify decoupling through unit tests.", "val_method": "code_submission"},
    ],
    "operating_systems": [
        {"stage": "learn", "title": "Processes, Threads, Concurrency & Context Switching", "desc": "Understand process control blocks (PCBs), user vs kernel mode, thread scheduling, and race conditions.", "val_method": "quiz"},
        {"stage": "learn", "title": "Memory Virtualization, Paging & Segmentation", "desc": "Learn virtual address spaces, page tables, TLBs, page faults, swapping, and memory fragmentation.", "val_method": "quiz"},
        {"stage": "practice", "title": "Thread Synchronization: Mutexes, Semaphores & Deadlocks", "desc": "Solve classic concurrency problems (Producer-Consumer, Dining Philosophers) preventing deadlocks.", "val_method": "practical_test"},
        {"stage": "practice", "title": "Inter-Process Communication (IPC) & File System I/O", "desc": "Experiment with pipes, UNIX domain sockets, shared memory, and inspect file descriptors.", "val_method": "practical_test"},
        {"stage": "build", "title": "Build a Thread-Safe Task Pool & Resource Allocator", "desc": "Implement a concurrent worker pool in Python/C++/Go managing work queues, mutex locking, and shutdown signals.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "OS Performance Diagnostics & Process Profiling", "desc": "Profile process CPU/memory usage, inspect system calls with strace, and diagnose I/O bottlenecks.", "val_method": "practical_test"},
    ],
    "computer_networks": [
        {"stage": "learn", "title": "OSI vs TCP/IP Models, Layer Encapsulation & Sockets", "desc": "Master packet encapsulation from Application layer (HTTP) down through Transport (TCP/UDP) to Network (IP).", "val_method": "quiz"},
        {"stage": "learn", "title": "TCP Handshake, Flow Control, Congestion & TLS Encryption", "desc": "Understand SYN/ACK connection establishment, sliding window, packet retransmission, and TLS handshakes.", "val_method": "quiz"},
        {"stage": "practice", "title": "Packet Capture & Protocol Inspection with Wireshark/tcpdump", "desc": "Capture real network packets, inspect HTTP headers, analyze TCP stream reassembly, and observe DNS lookup flows.", "val_method": "practical_test"},
        {"stage": "practice", "title": "DNS Resolution, Routing & Subnetting Calculations", "desc": "Calculate CIDR subnet masks, analyze routing tables, and trace DNS recursive resolution paths.", "val_method": "practical_test"},
        {"stage": "build", "title": "Develop a Custom TCP Client-Server Application", "desc": "Build a multi-client socket server handling concurrent connections, framing protocols, and graceful disconnects.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Network Troubleshooting & Latency Diagnostic Audit", "desc": "Diagnose network degradation using ping, traceroute, dig, netstat, and curl connection timing.", "val_method": "code_submission"},
    ],
    "dbms": [
        {"stage": "learn", "title": "DBMS Architecture: Storage Engines & Buffer Management", "desc": "Understand how relational engines store pages on disk, manage buffer pools, and execute reads/writes.", "val_method": "quiz"},
        {"stage": "learn", "title": "Concurrency Control, Lock Granularity & WAL Logging", "desc": "Master two-phase locking (2PL), shared vs exclusive locks, write-ahead logging, and crash recovery.", "val_method": "quiz"},
        {"stage": "practice", "title": "Transaction Anomaly Simulation & Isolation Testing", "desc": "Reproduce dirty reads, non-repeatable reads, and phantom reads under Read Committed vs Serializable levels.", "val_method": "practical_test"},
        {"stage": "build", "title": "Architect Database Replication, Partitioning & Failover Plan", "desc": "Draft high-availability specs detailing active-passive replication, horizontal sharding, and automated failover.", "val_method": "repo_inspection"},
        {"stage": "validate", "title": "Database Recovery & Deadlock Resolution Verification", "desc": "Simulate concurrent deadlocks, inspect lock graphs in system catalogs, and verify WAL recovery.", "val_method": "quiz"},
    ],
}


def _generate_dynamic_domain_tasks(
    canonical: str,
    target_role: str,
    category: str = "General",
) -> List[Dict[str, Any]]:
    """
    Dynamically generates a rich, highly specific 6-task curriculum for any skill
    based on its category, canonical name, and target role.
    """
    disp = canonical.replace("_", " ").title()
    cat_lower = (category or "").lower()

    if "database" in cat_lower or any(k in canonical.lower() for k in ("mongo", "redis", "db", "sql")):
        return [
            {"stage": "learn", "title": f"{disp} Architecture & Core Data Modeling", "desc": f"Learn {disp} data structures, connection pooling, schema constraints, and storage mechanics for {target_role}.", "val_method": "quiz"},
            {"stage": "learn", "title": f"Indexing, Query Optimization & Transaction Semantics in {disp}", "desc": f"Study index structures, query execution analysis, and concurrency controls in {disp}.", "val_method": "quiz"},
            {"stage": "practice", "title": f"{disp} Data Operations & Aggregation Challenges", "desc": f"Complete targeted exercises covering multi-table/collection queries, filters, and aggregations in {disp}.", "val_method": "practical_test"},
            {"stage": "build", "title": f"Build a Production Persistence Layer with {disp}", "desc": f"Implement an application repository layer integrating {disp} with automated migrations and connection management.", "val_method": "repo_inspection"},
            {"stage": "build", "title": f"Implement Caching & Query Performance Tuning for {disp}", "desc": f"Optimize read/write throughput, configure connection pooling, and benchmark response times under load.", "val_method": "repo_inspection"},
            {"stage": "validate", "title": f"{disp} Integrity & Failure Recovery Verification", "desc": f"Verify transactional data consistency, automated reconnection, and query plan benchmarks.", "val_method": "code_submission"},
        ]
    elif "devops" in cat_lower or "cloud" in cat_lower or any(k in canonical.lower() for k in ("aws", "gcp", "azure", "cloud", "infra", "k8s")):
        return [
            {"stage": "learn", "title": f"{disp} Core Architecture & Resource Hierarchy", "desc": f"Master core components, security permissions (IAM), and infrastructure primitives in {disp} for {target_role}.", "val_method": "quiz"},
            {"stage": "learn", "title": f"Networking, Isolation & Configuration in {disp}", "desc": f"Understand virtual networking, security boundaries, persistent volumes, and configuration patterns in {disp}.", "val_method": "quiz"},
            {"stage": "practice", "title": f"Deploying & Managing Infrastructure with {disp}", "desc": f"Configure and automate deployments, resource limits, and service connectivity using {disp}.", "val_method": "practical_test"},
            {"stage": "build", "title": f"Build an Automated Deployment Pipeline for {disp}", "desc": f"Deploy containerized microservices into {disp} with automated rollouts, health probes, and domain routing.", "val_method": "repo_inspection"},
            {"stage": "build", "title": f"Implement Monitoring, Logging & Resiliency Controls in {disp}", "desc": f"Set up log aggregation, metric alerts, and auto-restart / autoscaling triggers in {disp}.", "val_method": "repo_inspection"},
            {"stage": "validate", "title": f"{disp} Failure Mode & Chaos Verification", "desc": f"Simulate component failure and verify automated healing, traffic rerouting, and security compliance.", "val_method": "code_submission"},
        ]
    elif "ai" in cat_lower or "ml" in cat_lower:
        return [
            {"stage": "learn", "title": f"{disp} Mathematical Foundations & Model Mechanics", "desc": f"Understand core algorithms, loss functions, optimization techniques, and evaluation standards in {disp}.", "val_method": "quiz"},
            {"stage": "learn", "title": f"Feature Preprocessing & Pipeline Architecture in {disp}", "desc": f"Study data cleaning, feature scaling, encoding, and data leakage prevention for {disp}.", "val_method": "quiz"},
            {"stage": "practice", "title": f"{disp} Model Training & Hyperparameter Tuning", "desc": f"Train baseline and tuned models on real-world datasets with cross-validation and error analysis.", "val_method": "practical_test"},
            {"stage": "build", "title": f"Build an End-to-End Prediction Pipeline with {disp}", "desc": f"Implement complete pipeline from raw ingestion to model serialization and prediction service.", "val_method": "repo_inspection"},
            {"stage": "build", "title": f"Integrate Model Inference REST API & Monitoring", "desc": f"Deploy the trained model behind an API endpoint with input validation and latency monitoring.", "val_method": "repo_inspection"},
            {"stage": "validate", "title": f"Model Performance & Generalization Audit", "desc": f"Deliver validation report evaluating test metrics, confusion matrix, ROC-AUC, and feature importances.", "val_method": "code_submission"},
        ]
    else:
        return [
            {"stage": "learn", "title": f"{disp} Fundamentals, Mental Model & Syntax", "desc": f"Master the core concepts, primitives, and standard library conventions of {disp} for {target_role}.", "val_method": "quiz"},
            {"stage": "learn", "title": f"Idiomatic Patterns & Architecture in {disp}", "desc": f"Study production design patterns, error handling, modularity, and clean code practices in {disp}.", "val_method": "quiz"},
            {"stage": "practice", "title": f"{disp} Problem Solving & Practical Challenges", "desc": f"Complete progressive problem sets and exercises applying {disp} to realistic scenarios.", "val_method": "practical_test"},
            {"stage": "practice", "title": f"Advanced Techniques & Edge-Case Handling in {disp}", "desc": f"Handle concurrency, asynchronous workflows, or high-throughput boundaries with {disp}.", "val_method": "practical_test"},
            {"stage": "build", "title": f"Build a Production-Ready Application Module with {disp}", "desc": f"Develop a working, modular software component demonstrating end-to-end capability in {disp}.", "val_method": "repo_inspection"},
            {"stage": "validate", "title": f"Automated Testing & Verification Suite for {disp}", "desc": f"Write comprehensive tests verifying edge cases, boundary conditions, and performance in {disp}.", "val_method": "code_submission"},
        ]


def decompose_skill_into_tasks(
    canonical: str,
    total_hours: float,
    learner_state_classification: str = "UNKNOWN",
    target_role: str = "Software Engineer",
    granular: bool = False,
) -> List[Dict[str, Any]]:
    """
    Decompose a skill gap into structured tasks across the 4 stages (Learn -> Practice -> Build -> Validate).
    
    When granular=True (default):
    Emits 6 to 8 focused, actionable tasks (45-120 mins each) matching real-world engineering curriculum.
    
    When granular=False:
    Collapses into exactly 4 tasks (1 per stage) for backward compatibility with 4-stage unit tests.
    """
    key = _normalize_key(canonical)
    blocks = SKILL_DECOMPOSED_BLOCKS.get(key)
    resources = get_resources_for_skill(canonical)

    if not blocks:
        blocks = _generate_dynamic_domain_tasks(canonical=canonical, target_role=target_role)

    if not granular:
        # Collapse into 1 task per stage (Learn, Practice, Build, Validate)
        tmpl = get_template_for_skill(canonical)
        blocks = [
            {"stage": "learn", "title": f"Core {canonical} Fundamentals", "desc": f"Learn: {tmpl.get('learn', 'Core concepts and documentation')}.", "val_method": "quiz"},
            {"stage": "practice", "title": f"{canonical} Practical Exercises", "desc": f"Practice: {tmpl.get('practice', 'Complete guided exercises')}.", "val_method": "practical_test"},
            {"stage": "build", "title": f"Build a {canonical} Project", "desc": f"Build: {tmpl.get('project', 'Build a small practical project demonstrating capability')}.", "val_method": "repo_inspection"},
            {"stage": "validate", "title": f"Validate & Test {canonical} Knowledge", "desc": f"Validate: {tmpl.get('validate', 'Review, test, and document your work')}.", "val_method": "code_submission"},
        ]

    total_minutes = max(180, int(round(total_hours * 60)))

    # Ratio breakdown across the 4 stages based on learner state
    if learner_state_classification == "INFERRED":
        stage_ratios = {"learn": 0.15, "practice": 0.35, "build": 0.35, "validate": 0.15}
    elif learner_state_classification == "KNOWN":
        stage_ratios = {"learn": 0.10, "practice": 0.25, "build": 0.45, "validate": 0.20}
    else:
        # UNKNOWN: balanced foundational start
        stage_ratios = {"learn": 0.25, "practice": 0.35, "build": 0.25, "validate": 0.15}

    # Group blocks by stage
    tasks_by_stage: Dict[str, List[Dict[str, Any]]] = {"learn": [], "practice": [], "build": [], "validate": []}
    for b in blocks:
        stage = b.get("stage", "learn")
        if stage not in tasks_by_stage:
            tasks_by_stage[stage] = []
        tasks_by_stage[stage].append(b)

    tasks: List[Dict[str, Any]] = []
    accumulated_minutes = 0
    total_task_count = len(blocks)

    for stage in ("learn", "practice", "build", "validate"):
        stage_blocks = tasks_by_stage.get(stage, [])
        if not stage_blocks:
            continue
        stage_total_mins = int(round(total_minutes * stage_ratios[stage]))
        mins_per_task = max(30, int(round((stage_total_mins / len(stage_blocks)) / 15.0) * 15))

        for b in stage_blocks:
            is_last_task = (len(tasks) == total_task_count - 1)
            if is_last_task:
                task_minutes = max(30, total_minutes - accumulated_minutes)
            else:
                task_minutes = mins_per_task
                accumulated_minutes += task_minutes

            task_resources = resources if b["stage"] in ("learn", "practice") else resources[:1]

            tasks.append({
                "task_type": b["stage"],
                "title": b["title"],
                "description": f"{b['desc']} (Focus for {target_role}).",
                "estimated_minutes": task_minutes,
                "validation_method": b["val_method"],
                "resources": task_resources,
                "why_this_task": f"Progressive stage ({b['stage'].upper()}) designed to close your {canonical} gap for {target_role} through verified capability.",
            })

    return tasks
