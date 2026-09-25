/**
 * Turns the data INAURA already stores (analysis, gaps, evidence, roadmap) into what the
 * dashboard shows. Pure functions only — no fetching — so the view stays simple and testable.
 */
import type { AnalysisResult, SkillGap } from "../../services/analysis";
import type { AvailableAssessment } from "../../services/assessment";
import type { Certification, Evidence, Project } from "../../services/evidence";
import type { Roadmap, RoadmapTask, RoadmapWeek } from "../../services/roadmap";

/* ------------------------------------------------------------------ */
/* Skill signal: how far along the evidence ladder each required skill is */
/* ------------------------------------------------------------------ */

export type SignalStage = "none" | "claimed" | "evidence" | "verified";

export const SIGNAL_STAGES: { key: SignalStage; label: string; hint: string }[] = [
  { key: "none", label: "No evidence", hint: "Required for the role, but nothing shows it yet" },
  { key: "claimed", label: "Claimed", hint: "Mentioned by you, with little independent proof" },
  { key: "evidence", label: "Some evidence", hint: "Seen in your work, not yet strong enough to confirm" },
  { key: "verified", label: "Verified", hint: "Backed by strong evidence or a passed assessment" },
];

export type SignalSkill = { name: string; stage: SignalStage; gap: SkillGap };

export const skillName = (g: SkillGap) =>
  g.skills?.display_name || g.skills?.canonical_name || g.canonical_name || g.skill || "Unnamed skill";

export function classifySkill(g: SkillGap): SignalStage {
  const noEvidence =
    g.is_overridden ||
    g.evidence_state === "no_evidence" ||
    g.evidence_state === "user_override" ||
    (g.current_proficiency === 0 && g.confidence === 0);
  if (noEvidence) return "none";
  if (g.has_assessment && (g.assessment_score ?? 0) >= 0.6) return "verified";
  // Same thresholds the Skill Analysis page uses for its quadrants
  if (g.quadrant === "strong_validated" || (g.current_proficiency >= 0.6 && g.confidence >= 0.5)) return "verified";
  if (g.quadrant === "unverified_claim" || (g.current_proficiency >= 0.6 && g.confidence < 0.5)) return "claimed";
  return "evidence";
}

export function buildSignal(gaps: SkillGap[]) {
  const skills: SignalSkill[] = gaps
    .filter((g) => !g.is_portfolio)
    .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0))
    .map((g) => ({ name: skillName(g), stage: classifySkill(g), gap: g }));
  const byStage = Object.fromEntries(
    SIGNAL_STAGES.map((s) => [s.key, skills.filter((k) => k.stage === s.key)])
  ) as Record<SignalStage, SignalSkill[]>;
  return { skills, byStage, total: skills.length };
}

/* ------------------------------------------------------------------ */
/* Evidence coverage                                                   */
/* ------------------------------------------------------------------ */

export type CoverageState = "verified" | "included" | "added" | "failed" | "missing";
/** noun: how actions refer to it, e.g. "LeetCode profile" */
export type CoverageItem = { key: string; label: string; noun: string; detail: string; state: CoverageState; to: string; cta: string };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const PROVIDER_NAME: Record<string, string> = { leetcode: "LeetCode", codeforces: "Codeforces" };

const pickBest = (items: Evidence[]): Evidence | undefined =>
  items.find((e) => e.verification_status === "verified") ??
  items.find((e) => e.verification_status !== "failed") ??
  items[0];

export function buildCoverage(evidence: Evidence[], projects: Project[], certs: Certification[]) {
  const active = evidence.filter((e) => !e.is_excluded);
  const ofType = (...types: string[]) => active.filter((e) => types.includes(e.evidence_type));

  const fromEvidence = (key: string, label: string, noun: string, types: string[], to: string, emptyDetail: string, cta: string): CoverageItem => {
    const best = pickBest(ofType(...types));
    if (!best) return { key, label, noun, detail: emptyDetail, state: "missing", to, cta };
    const state: CoverageState =
      best.verification_status === "verified" ? "verified" : best.verification_status === "failed" ? "failed" : "added";
    const provider = types.length > 1 ? `${PROVIDER_NAME[best.evidence_type] ?? best.evidence_type} ` : "";
    const detail =
      state === "verified" ? `${provider}verified` : state === "failed" ? `${provider}couldn’t be verified` : `${provider}added, not verified`;
    const specificNoun = types.length > 1 ? `${PROVIDER_NAME[best.evidence_type] ?? label} profile` : noun;
    return { key, label, noun: specificNoun, detail, state, to, cta: state === "failed" ? `Fix your ${specificNoun}` : cta };
  };

  const items: CoverageItem[] = [
    fromEvidence("github", "GitHub", "GitHub profile", ["github"], "/analysis#profile-urls", "Shows the code you’ve written", "Add GitHub"),
    fromEvidence("practice", "Coding practice", "coding profile", ["leetcode", "codeforces"], "/analysis#profile-urls", "LeetCode or Codeforces", "Add a coding profile"),
    fromEvidence("resume", "Resume", "resume", ["resume"], "/analysis#file-evidence", "Your latest CV", "Upload your resume"),
    fromEvidence("coursework", "Coursework", "syllabus", ["syllabus"], "/analysis#file-evidence", "College syllabus", "Upload your syllabus"),
    projects.some((p) => !p.is_excluded) || ofType("project_doc").length
      ? { key: "projects", label: "Projects", noun: "project", detail: plural(projects.filter((p) => !p.is_excluded).length || 1, "project") + " added", state: "included", to: "/analysis#projects", cta: "Add a project" }
      : { key: "projects", label: "Projects", noun: "project", detail: "What you’ve built", state: "missing", to: "/analysis#projects", cta: "Add a project" },
    certs.length || ofType("certification_file").length
      ? { key: "certs", label: "Certifications", noun: "certificate", detail: plural(certs.length || 1, "certificate") + " added", state: "included", to: "/analysis#certifications", cta: "Add a certificate" }
      : { key: "certs", label: "Certifications", noun: "certificate", detail: "Courses you’ve completed", state: "missing", to: "/analysis#certifications", cta: "Add a certificate" },
  ];
  // Projects and certificates have no verification step, so adding them is enough
  const complete = items.filter((i) => i.state === "verified" || i.state === "included");
  const present = items.filter((i) => i.state !== "missing");
  return {
    items,
    presentCount: present.length,
    completeCount: complete.length,
    percent: Math.round((present.length / items.length) * 100),
  };
}

/* ------------------------------------------------------------------ */
/* Roadmap                                                             */
/* ------------------------------------------------------------------ */

export function currentWeek(roadmap: Roadmap | null, weeks: RoadmapWeek[]) {
  if (!weeks.length) return null;
  return (
    weeks.find((w) => w.week_number === roadmap?.current_week_index) ??
    weeks.find((w) => w.status === "current" || w.status === "behind_schedule") ??
    weeks.find((w) => w.status !== "completed") ??
    weeks[weeks.length - 1]
  );
}

/** A window of weeks around the current one, so the preview always shows where you are. */
export function roadmapWindow(roadmap: Roadmap | null, weeks: RoadmapWeek[], size = 4) {
  const sorted = [...weeks].sort((a, b) => a.week_number - b.week_number);
  const cur = currentWeek(roadmap, sorted);
  const idx = cur ? sorted.indexOf(cur) : 0;
  const start = Math.max(0, Math.min(idx - 1, sorted.length - size));
  return { shown: sorted.slice(start, start + size), current: cur, total: sorted.length };
}

/* ------------------------------------------------------------------ */
/* Next actions                                                        */
/* ------------------------------------------------------------------ */

export type NextAction =
  | { kind: "task"; id: string; title: string; meta: string; task: RoadmapTask }
  | { kind: "link"; id: string; title: string; meta: string; to: string };

export function buildActions(args: {
  analysis: AnalysisResult | null;
  roadmap: Roadmap | null;
  weeks: RoadmapWeek[];
  coverage: CoverageItem[];
  assessable: AvailableAssessment[];
  /** Revision cards that have come round again */
  revisionDue?: number;
  limit?: number;
}): NextAction[] {
  const { analysis, roadmap, weeks, coverage, assessable, revisionDue = 0, limit = 5 } = args;
  const actions: NextAction[] = [];

  const week = currentWeek(roadmap, weeks);
  const openTasks = (week?.tasks ?? [])
    .filter((t) => t.status !== "completed" && t.status !== "skipped")
    .sort((a, b) => a.sequence_order - b.sequence_order)
    .slice(0, 3);
  for (const t of openTasks) {
    actions.push({
      kind: "task",
      id: `task-${t.id}`,
      title: t.title,
      meta: [t.skill_name, t.estimated_minutes ? `${t.estimated_minutes} min` : ""].filter(Boolean).join(", "),
      task: t,
    });
  }

  const cov = (key: string) => coverage.find((c) => c.key === key);
  const failed = coverage.find((c) => c.state === "failed");
  if (failed) {
    actions.push({ kind: "link", id: `fix-${failed.key}`, title: `Fix your ${failed.noun} link`, meta: "It couldn’t be verified", to: failed.to });
  }
  const unverified = coverage.find((c) => c.state === "added" && (c.key === "github" || c.key === "practice"));
  if (unverified) {
    actions.push({ kind: "link", id: `verify-${unverified.key}`, title: `Verify your ${unverified.noun}`, meta: "Unverified profiles count for less", to: unverified.to });
  }

  // Evidence in, no analysis yet: running it is the one step that turns the rest on.
  // (With no evidence at all, adding some comes first — see the missing sources below.)
  if (!analysis && coverage.some((c) => c.state !== "missing")) {
    actions.unshift({ kind: "link", id: "run-analysis", title: "Run your analysis", meta: "See where your evidence puts you", to: "/analysis" });
  }

  if (analysis && !roadmap) {
    actions.push({ kind: "link", id: "roadmap", title: "Generate your roadmap", meta: "A weekly plan built from your gaps", to: "/roadmap" });
  }

  // Revision is where the roadmap's skills are kept from slipping
  if (revisionDue > 0) {
    actions.push({
      kind: "link",
      id: "revision",
      title: `Revise ${revisionDue} card${revisionDue === 1 ? "" : "s"}`,
      meta: "A few minutes on skills you’re building",
      to: "/revision",
    });
  }

  const assessment = assessable
    .filter((a) => !a.already_assessed)
    .sort((a, b) => b.priority_score - a.priority_score)[0];
  if (assessment) {
    actions.push({
      kind: "link",
      id: `assess-${assessment.skill_key}`,
      title: `Prove your ${assessment.skill} skills`,
      meta: assessment.reason_label || "Short assessment",
      to: "/skill-assessment",
    });
  }

  for (const [key, title, meta] of [
    ["github", "Add your GitHub profile", "The strongest evidence for most roles"],
    ["coursework", "Upload your college syllabus", "Credits what you’ve studied"],
    ["projects", "Add a project", "Show something you’ve built"],
    ["resume", "Upload your resume", "Helps INAURA find skills to check"],
  ] as const) {
    const c = cov(key);
    if (c?.state === "missing") {
      actions.push({ kind: "link", id: `add-${key}`, title, meta, to: c.to });
    }
  }

  return actions.slice(0, limit);
}

/* ------------------------------------------------------------------ */
/* Insights and activity                                               */
/* ------------------------------------------------------------------ */

export type Tone = "positive" | "attention" | "neutral";
export type Insight = { id: string; tone: Tone; title: string; detail: string; to: string };

export function buildInsights(signal: ReturnType<typeof buildSignal>, analysis: AnalysisResult | null): Insight[] {
  if (!analysis) return [];
  const insights: Insight[] = [];
  const target = signal.skills.map((s) => s.gap);

  const biggest = target.find((g) => g.gap > 0 && (g.priority_category === "critical" || g.priority_category === "high")) ?? target.find((g) => g.gap > 0);
  if (biggest) {
    insights.push({
      id: "gap",
      tone: "attention",
      title: `${skillName(biggest)} is your biggest gap`,
      detail: biggest.actionable_advice || biggest.explanation || `${analysis.target_role} roles expect it, and your evidence doesn’t show it yet.`,
      to: "/analysis/results",
    });
  }

  const missing = signal.byStage.none.filter((s) => s.gap !== biggest);
  if (missing.length) {
    const names = missing.slice(0, 3).map((s) => s.name);
    insights.push({
      id: "missing",
      tone: "attention",
      title: missing.length === 1 ? `${names[0]} has no evidence yet` : `${missing.length} required skills have no evidence yet`,
      detail:
        missing.length === 1
          ? missing[0].gap.explanation || "Add a project or profile that uses it."
          : `Including ${names.join(", ")}. A project or assessment for any of them will raise your readiness.`,
      to: "/analysis/results",
    });
  }

  const claimed = signal.byStage.claimed;
  if (claimed.length) {
    insights.push({
      id: "claimed",
      tone: "neutral",
      title: claimed.length === 1 ? `${claimed[0].name} relies on your word alone` : `${claimed.length} skills rely on your word alone`,
      detail: `${claimed.slice(0, 3).map((s) => s.name).join(", ")} ${claimed.length === 1 ? "appears" : "appear"} in what you’ve told INAURA, but little independent evidence backs ${claimed.length === 1 ? "it" : "them"}. An assessment can confirm ${claimed.length === 1 ? "it" : "them"}.`,
      to: "/skill-assessment",
    });
  }

  const strongest = signal.byStage.verified[0];

  if (strongest) {
    const sources = strongest.gap.evidence_sources?.map((s) => s.source_label).filter(Boolean).slice(0, 2) ?? [];
    insights.push({
      id: "strength",
      tone: "positive",
      title: `${strongest.name} is confirmed`,
      detail: sources.length
        ? `Backed by ${sources.join(" and ")}. ${strongest.gap.explanation ?? ""}`.trim()
        : strongest.gap.explanation || "Your evidence meets what the role asks for.",
      to: "/analysis/results",
    });
  }
  return insights;
}

export type ActivityEvent = { id: string; tone: Tone; text: string; at: string };

const EVIDENCE_LABEL: Record<string, string> = {
  github: "GitHub profile",
  leetcode: "LeetCode profile",
  codeforces: "Codeforces profile",
  kaggle: "Kaggle profile",
  linkedin: "LinkedIn profile",
  resume: "Resume",
  syllabus: "College syllabus",
  certification_file: "Certificate file",
  project_doc: "Project document",
};

export function buildActivity(args: {
  analysis: AnalysisResult | null;
  evidence: Evidence[];
  projects: Project[];
  certs: Certification[];
  roadmap: Roadmap | null;
  weeks: RoadmapWeek[];
  limit?: number;
}): ActivityEvent[] {
  const { analysis, evidence, projects, certs, roadmap, weeks, limit = 5 } = args;
  const events: ActivityEvent[] = [];

  if (analysis) {
    events.push({
      id: `analysis-${analysis.id}`,
      tone: "neutral",
      text: `Analysis updated: ${Math.round(analysis.readiness_score * 100)}% ready`,
      at: analysis.created_at,
    });
  }
  for (const e of evidence) {
    const label = EVIDENCE_LABEL[e.evidence_type] ?? "Evidence";
    events.push({ id: `ev-${e.id}`, tone: "neutral", text: `${label} added`, at: e.created_at });
    if (e.verification_status === "verified" && e.verified_at) {
      events.push({ id: `ev-v-${e.id}`, tone: "positive", text: `${label} verified`, at: e.verified_at });
    } else if (e.verification_status === "failed") {
      events.push({ id: `ev-f-${e.id}`, tone: "attention", text: `${label} couldn’t be verified`, at: e.updated_at });
    }
  }
  for (const p of projects) events.push({ id: `pr-${p.id}`, tone: "neutral", text: `Project added: ${p.name}`, at: p.created_at });
  for (const c of certs) events.push({ id: `ce-${c.id}`, tone: "neutral", text: `Certificate added: ${c.name}`, at: c.created_at });
  if (roadmap?.created_at) {
    events.push({ id: `rm-${roadmap.id}`, tone: "neutral", text: `Roadmap created: ${roadmap.total_weeks ?? roadmap.estimated_weeks} weeks`, at: roadmap.created_at });
  }
  for (const w of weeks) {
    for (const t of w.tasks ?? []) {
      if (t.status === "completed" && t.completed_at) {
        events.push({ id: `task-${t.id}`, tone: "positive", text: `Completed: ${t.title}`, at: t.completed_at });
      }
    }
  }

  return events
    .filter((e) => e.at && !Number.isNaN(Date.parse(e.at)))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, limit);
}

/* ------------------------------------------------------------------ */
/* Small formatting helpers                                            */
/* ------------------------------------------------------------------ */

export function relativeDay(iso: string, now = new Date()) {
  const then = new Date(iso);
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(then)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function greeting(now = new Date()) {
  const h = now.getHours();
  if (h < 5) return "Working late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

/** One plain sentence that sums up where the student stands right now. */
export function summaryLine(args: {
  analysis: AnalysisResult | null;
  signal: ReturnType<typeof buildSignal>;
  coveragePresent: number;
}) {
  const { analysis, signal, coveragePresent } = args;
  if (!analysis) {
    return coveragePresent
      ? "Your evidence is in. Run an analysis to see how ready you are for your target role."
      : "Add some evidence of your skills and INAURA will show you where you stand.";
  }
  const verified = signal.byStage.verified.length;
  const top = signal.skills.find((s) => s.gap.gap > 0);
  const lead =
    signal.total > 0
      ? `${verified} of the ${signal.total} skills ${analysis.target_role} roles ask for ${verified === 1 ? "is" : "are"} verified.`
      : `Your readiness for ${analysis.target_role} is ${Math.round(analysis.readiness_score * 100)}%.`;
  return top ? `${lead} ${top.name} is the one to work on next.` : lead;
}
