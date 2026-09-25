/**
 * What the search bar can find, and how a typed query is matched against it.
 *
 * Everything here comes from data the app has already loaded for its pages, so searching
 * costs nothing and works the moment you start typing. Pure functions only, no React.
 */

export type SearchKind = "Page" | "Career" | "Skill" | "Gap" | "Plan" | "Resource" | "Project" | "Certificate";

export type SearchResult = {
  id: string;
  /** The line you read */
  label: string;
  /** The quieter second line, e.g. what a role is for */
  detail?: string;
  kind: SearchKind;
  /** Where picking it takes you */
  to: string;
  /** Other words that should find it, e.g. "cv" for the resume page */
  keywords?: string[];
};

/** Ties are broken by this order, so a page beats a deep item of the same score */
const KIND_ORDER: SearchKind[] = ["Page", "Career", "Skill", "Gap", "Plan", "Resource", "Project", "Certificate"];

/** The app's own pages, always searchable whether or not your data has loaded */
export const PAGES: SearchResult[] = [
  {
    id: "page:career-track",
    label: "Career Track",
    detail: "Your path to the role you're aiming for",
    kind: "Page",
    to: "/career-track",
    keywords: ["home", "path", "readiness", "progress"],
  },
  {
    id: "page:analysis",
    label: "Evidence",
    detail: "Add GitHub, LeetCode, your resume and projects — then run your analysis",
    kind: "Page",
    to: "/analysis",
    keywords: ["run analysis", "github", "linkedin", "leetcode", "notion", "upload", "sources", "resume", "files"],
  },
  {
    id: "page:results",
    label: "Analysis",
    detail: "Your readiness, priority gaps and skill quadrants",
    kind: "Page",
    to: "/analysis/results",
    keywords: ["results", "gaps", "quadrants", "overview", "score", "report", "readiness"],
  },
  {
    id: "page:priority-gaps",
    label: "Priority Gaps",
    detail: "The skills furthest from what your role needs",
    kind: "Page",
    to: "/analysis/results#priority-gaps",
    keywords: ["gaps", "weak", "missing", "analysis"],
  },
  {
    id: "page:skill-quadrants",
    label: "Skill Quadrants",
    detail: "Each skill by strength and by how sure INAURA is",
    kind: "Page",
    to: "/analysis/results#skill-quadrants",
    keywords: ["quadrant", "confidence", "analysis"],
  },
  {
    id: "page:capabilities",
    label: "Capability Map",
    detail: "What each skill involves, and what your evidence shows",
    kind: "Page",
    to: "/analysis/capabilities",
    keywords: ["capabilities", "skills", "detail", "map"],
  },
  {
    id: "page:skill-assessments",
    label: "Skill Assessment",
    detail: "Prove a skill with a short check",
    kind: "Page",
    to: "/skill-assessment",
    keywords: ["quiz", "test", "validate", "assessments", "prove"],
  },
  {
    id: "page:dsa",
    label: "DSA",
    detail: "Data structures and algorithms checklist",
    kind: "Page",
    to: "/skill-assessment/dsa",
    keywords: ["algorithms", "data structures", "problems", "leetcode", "neetcode"],
  },
  {
    id: "page:interview",
    label: "Mock Interview",
    detail: "Practise answering out loud",
    kind: "Page",
    to: "/interview",
    keywords: ["practice", "questions", "voice", "hr", "technical"],
  },
  {
    id: "page:ats",
    label: "Resume",
    detail: "ATS tester: how your resume reads to a screener",
    kind: "Page",
    to: "/resume/ats-tester",
    keywords: ["ats", "cv", "score", "keywords", "applicant tracking"],
  },
  {
    id: "page:roadmap",
    label: "Roadmap",
    detail: "Your week-by-week plan",
    kind: "Page",
    to: "/roadmap",
    keywords: ["plan", "weeks", "tasks", "schedule", "study"],
  },
  {
    id: "page:revision",
    label: "Revision",
    detail: "A few minutes a day on the skills you're building",
    kind: "Page",
    to: "/revision",
    keywords: ["flashcards", "cards", "recall", "practice", "revise"],
  },

  {
    id: "page:profile",
    label: "Profile",
    detail: "Your details and study hours",
    kind: "Page",
    to: "/profile",
    keywords: ["account", "settings", "name", "hours"],
  },
];

/** The already-loaded data the index is built from — all of it optional, since pages load separately */
export type IndexSources = {
  roles?: { id: string; title: string; description?: string }[];
  /** Skills on the career track you're currently on */
  skills?: { id: string; name: string; category?: string }[];
  careerId?: string;
  gaps?: { skill: string; detail?: string }[];
  projects?: { id: string; name: string; technologies?: string[] }[];
  certificates?: { id: string; name: string; issuer?: string }[];
  /** Reading and practice attached to your roadmap tasks */
  resources?: { id: string; title: string; skill?: string }[];
  weeks?: { id: string; number: number; title: string; tasks?: { id: string; title: string; skill?: string }[] }[];
};

/** Everything searchable right now, pages first */
export function buildIndex(sources: IndexSources = {}): SearchResult[] {
  const out: SearchResult[] = [...PAGES];

  for (const role of sources.roles ?? []) {
    out.push({
      id: `role:${role.id}`,
      label: role.title,
      detail: role.description,
      kind: "Career",
      to: `/career-track/${role.id}`,
      keywords: ["career", "role", "track"],
    });
  }

  // Skills only lead somewhere while we know which career track they belong to
  if (sources.careerId) {
    for (const skill of sources.skills ?? []) {
      out.push({
        id: `skill:${skill.id}`,
        label: skill.name,
        detail: skill.category ? `Skill · ${skill.category}` : "Skill on your career track",
        kind: "Skill",
        to: `/career-track/${sources.careerId}/${skill.id}`,
      });
    }
  }

  for (const gap of sources.gaps ?? []) {
    out.push({
      id: `gap:${gap.skill}`,
      label: gap.skill,
      detail: gap.detail ?? "A gap between where you are and what the role asks for",
      kind: "Gap",
      to: "/analysis/results#priority-gaps",
      keywords: ["gap", "skill", "missing", "weak"],
    });
  }

  for (const week of sources.weeks ?? []) {
    out.push({
      id: `week:${week.id}`,
      label: `Week ${week.number} — ${week.title}`,
      detail: "In your roadmap",
      kind: "Plan",
      to: "/roadmap",
      keywords: ["week", "plan", "roadmap"],
    });
    for (const task of week.tasks ?? []) {
      out.push({
        id: `task:${task.id}`,
        label: task.title,
        detail: `Week ${week.number}${task.skill ? ` · ${task.skill}` : ""}`,
        kind: "Plan",
        to: "/roadmap",
        keywords: ["task", "todo", "roadmap"],
      });
    }
  }

  for (const project of sources.projects ?? []) {
    out.push({
      id: `project:${project.id}`,
      label: project.name,
      detail: project.technologies?.length ? project.technologies.join(", ") : "Your project",
      kind: "Project",
      to: "/analysis#projects",
      keywords: ["project", ...(project.technologies ?? [])],
    });
  }

  for (const resource of sources.resources ?? []) {
    out.push({
      id: `resource:${resource.id}`,
      label: resource.title,
      detail: resource.skill ? `Resource · ${resource.skill}` : "Resource in your roadmap",
      kind: "Resource",
      to: "/roadmap",
      keywords: ["resource", "learn", "reading", "course", "tutorial"],
    });
  }

  for (const cert of sources.certificates ?? []) {
    out.push({
      id: `cert:${cert.id}`,
      label: cert.name,
      detail: cert.issuer,
      kind: "Certificate",
      to: "/analysis#certifications",
      keywords: ["certificate", "certification", "course"],
    });
  }

  return out;
}

const norm = (s: string) => s.toLowerCase().trim();
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Where in a piece of text a term sits, as a score. 0 means it isn't there. */
function place(text: string, term: string): number {
  if (text === term) return 120;
  if (text.startsWith(term)) return 90;
  // The start of any word in it, so "int" finds "Mock Interview"
  if (new RegExp(`\\b${escape(term)}`).test(text)) return 65;
  if (text.includes(term)) return 35;
  return 0;
}

/**
 * Where a term landed, trying the other of singular and plural when it isn't there as typed —
 * so "skills" finds a Skill and "interview" finds Mock Interviews.
 */
function hit(text: string, term: string): number {
  const t = norm(text);
  if (!t) return 0;
  const direct = place(t, term);
  if (direct) return direct;
  const other = term.endsWith("s") ? term.slice(0, -1) : `${term}s`;
  return other.length > 2 ? Math.round(place(t, other) * 0.95) : 0;
}

/** How well one result answers one term; 0 if it doesn't at all */
function scoreTerm(item: SearchResult, term: string): number {
  const label = hit(item.label, term);
  if (label) return label;
  const keyword = Math.max(0, ...(item.keywords ?? []).map((k) => hit(k, term)));
  if (keyword) return Math.round(keyword * 0.5);
  const detail = hit(item.detail ?? "", term);
  if (detail) return Math.round(detail * 0.3);
  return hit(item.kind, term) ? 10 : 0;
}

/**
 * The best matches for what's been typed, strongest first.
 * Every word typed has to match something, so more words narrow rather than widen.
 */
export function search(query: string, index: SearchResult[], limit = 8): SearchResult[] {
  const terms = norm(query).split(/\s+/).filter(Boolean);
  if (!terms.length) return [];

  const scored: { item: SearchResult; score: number }[] = [];
  for (const item of index) {
    let total = 0;
    for (const term of terms) {
      const s = scoreTerm(item, term);
      if (!s) {
        total = 0;
        break;
      }
      total += s;
    }
    if (total > 0) scored.push({ item, score: total });
  }

  scored.sort(
    (a, b) =>
      b.score - a.score ||
      KIND_ORDER.indexOf(a.item.kind) - KIND_ORDER.indexOf(b.item.kind) ||
      a.item.label.length - b.item.label.length ||
      a.item.label.localeCompare(b.item.label)
  );
  return scored.slice(0, limit).map((s) => s.item);
}
