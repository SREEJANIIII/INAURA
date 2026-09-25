/**
 * What goes on the cards, and which of them you're shown today.
 *
 * Three rules decide everything here.
 *
 * A card is only worth asking if it has an answer you can mark yourself against. "How would
 * you teach yourself X?" is a journal prompt, not recall, so nothing like it is built.
 *
 * A card knows why it exists. Every one carries the reason INAURA put it in front of you —
 * a gap in your analysis, a week on your roadmap, evidence it did or didn't find. That line
 * is what ties revision to the rest of the product instead of leaving it a bolt-on.
 *
 * And the order is INAURA's own: new cards arrive worst-gap first, and skills your roadmap has
 * you on this week come before the rest. Revising what you already know is the comfortable
 * mistake — this deck pushes the other way.
 */
// Extension included so this module resolves the same way in the bundler and in the
// test runner; the scheduler is a runtime dependency here, not just a type.
import { isDue, isNew, type CardProgress } from "./schedule.ts";

/**
 * What a card is asking of you. Each one comes from a different part of INAURA, and the
 * label on the card says which, so revision reads as one system rather than a quiz.
 */
export type RevisionKind = "concept" | "industry" | "gap" | "evidence" | "roadmap" | "pattern";

export const KIND_LABEL: Record<RevisionKind, string> = {
  concept: "Concept",
  industry: "Industry expects",
  gap: "Skill gap",
  evidence: "Your evidence",
  roadmap: "Roadmap",
  pattern: "Pattern",
};

export type RevisionCard = {
  id: string;
  kind: RevisionKind;
  /** The skill or topic it belongs to — the big name on the card */
  topic: string;
  /** What's asked, before the reveal */
  question: string;
  /** The short form of the answer */
  answer: string;
  /** The checkable part: what you should have said */
  points: string[];
  /** Why INAURA is asking you this, in one line */
  why: string;
  /** How hard or how urgent, where INAURA knows — shown on the card face */
  level?: string;
  link?: string;
  /** Higher comes first among new cards */
  weight: number;
};

/* ---------------- Sources ---------------- */

export type DeckSkill = {
  skill: string;
  slug: string;
  /** 0-1 or 0-100; how far below the bar this skill is, bigger meaning worse */
  priority?: number;
  proficiency?: number;
  confidence?: number;
  status?: string;
  priority_category?: string;
  capabilities?: {
    id: string;
    title: string;
    summary?: string;
    observable_abilities?: string[];
    knowledge_statement?: string;
  }[];
  industry_expectations?: { capability_id: string; title: string; detail: string }[];
  missing_capabilities?: { id: string; title: string; next_actions?: string[]; priority_category?: string }[];
  demonstrated_capabilities?: { id: string; title: string }[];
  evidence_sources?: { provider?: string; repository?: string; reason?: string }[];
};

export type DeckDsa = {
  id: string;
  title: string;
  topic: string;
  pattern: string;
  difficulty: string;
  why_it_matters: string;
  neetcode_url?: string;
  solved: boolean;
};

export type DeckTask = {
  id: string;
  title: string;
  description?: string;
  skill_name?: string;
  week: number;
  current: boolean;
};

export type DeckSources = {
  skills?: DeckSkill[];
  dsa?: DeckDsa[];
  /** Tasks from the weeks you're on now */
  tasks?: DeckTask[];
  role?: string | null;
};

const clean = (s: string | undefined) => (s || "").trim();
const norm = (s: string) => clean(s).toLowerCase();
const pct = (n: number | undefined) => (typeof n === "number" ? Math.round(n <= 1 ? n * 100 : n) : null);
const list = (items: string[]) => items.map(clean).filter(Boolean);

/* ---------------- Building the cards ---------------- */

/**
 * Every card INAURA can ask you, from what it already knows about your skills, your evidence
 * and your plan. Nothing here talks to the network: it reads data the other pages loaded.
 */
export function buildDeck(sources: DeckSources = {}): RevisionCard[] {
  const cards: RevisionCard[] = [];
  const role = clean(sources.role || "") || "the role you're aiming for";
  const onPlan = new Set((sources.tasks || []).filter((t) => t.current).map((t) => norm(t.skill_name || "")));

  for (const skill of sources.skills || []) {
    const name = clean(skill.skill);
    if (!name) continue;

    const gap = typeof skill.priority === "number" ? (skill.priority > 1 ? skill.priority / 100 : skill.priority) : 0.5;
    const known = pct(skill.proficiency);
    const confidence = pct(skill.confidence);
    const planned = onPlan.has(norm(name));
    const base = gap * 2 + (planned ? 1.5 : 0);
    // Title-cased so "critical" reads as a label rather than a shout
    const urgency = clean(skill.priority_category)
      ? clean(skill.priority_category!).charAt(0).toUpperCase() + clean(skill.priority_category!).slice(1).toLowerCase()
      : undefined;

    /** The line that says why this card exists, built from whatever INAURA actually knows */
    const why = (extra?: string) => {
      const parts: string[] = [];
      if (planned) parts.push("your roadmap has you on this now");
      if (known !== null) parts.push(`you're at ${known}% against what ${role} asks`);
      else parts.push(`${role} asks for this`);
      if (confidence !== null && confidence < 50) parts.push("and little has confirmed it");
      const line = parts.join(", ");
      return extra ? `${extra} — ${line}` : line.charAt(0).toUpperCase() + line.slice(1);
    };

    for (const cap of skill.capabilities || []) {
      const points = list(cap.observable_abilities || []).slice(0, 5);
      // Without the abilities there is nothing to check yourself against, so no card
      if (!points.length) continue;
      cards.push({
        id: `concept:${skill.slug}:${cap.id}`,
        kind: "concept",
        topic: name,
        question: `${clean(cap.title)} — what should you actually be able to do?`,
        answer: clean(cap.summary) || clean(cap.knowledge_statement) || `What ${name} asks of you here:`,
        points,
        why: why(),
        level: urgency,
        weight: base + 1,
      });
    }

    for (const exp of skill.industry_expectations || []) {
      const detail = clean(exp.detail);
      if (!detail) continue;
      cards.push({
        id: `industry:${skill.slug}:${exp.capability_id}`,
        kind: "industry",
        topic: name,
        question: `${clean(exp.title)} — what does industry expect you to know here?`,
        answer: detail,
        points: [],
        why: why("Taken from the benchmarks INAURA holds for this role"),
        level: urgency,
        weight: base + 0.4,
      });
    }

    for (const miss of skill.missing_capabilities || []) {
      const actions = list(miss.next_actions || []).slice(0, 4);
      if (!actions.length) continue;
      cards.push({
        id: `gap:${skill.slug}:${miss.id}`,
        kind: "gap",
        topic: name,
        question: `${clean(miss.title)} — what's still missing, and what would close it?`,
        answer: `Nothing you've submitted covers this yet.`,
        points: actions,
        why: why(clean(miss.priority_category) ? `Flagged ${norm(miss.priority_category!)} in your analysis` : undefined),
        level: clean(miss.priority_category)
          ? clean(miss.priority_category!).charAt(0).toUpperCase() + clean(miss.priority_category!).slice(1).toLowerCase()
          : urgency,
        // The gaps are the point of the product, so they carry the most weight
        weight: base + 1.6,
      });
    }

    const shown = list((skill.demonstrated_capabilities || []).map((d) => d.title)).slice(0, 4);
    if (shown.length) {
      const where = list(
        (skill.evidence_sources || []).map((e) => clean(e.repository) || clean(e.provider))
      ).slice(0, 3);
      cards.push({
        id: `evidence:${skill.slug}`,
        kind: "evidence",
        topic: name,
        question: `What have you actually shown for ${name}?`,
        answer: where.length
          ? `INAURA found this in ${where.join(", ")}.`
          : "INAURA found this in the evidence you've added.",
        points: shown,
        why: why("Worth knowing cold — this is what you'd claim in an interview"),
        level: "Proven",
        weight: base * 0.5 + 0.3,
      });
    }
  }

  for (const task of sources.tasks || []) {
    const title = clean(task.title);
    const skill = clean(task.skill_name);
    if (!title || !skill) continue;
    cards.push({
      id: `roadmap:${task.id}`,
      kind: "roadmap",
      topic: skill,
      question: `${skill} — what does your plan have you doing next?`,
      answer: title,
      points: clean(task.description) ? [clean(task.description)] : [],
      why: `Week ${task.week} of your ${role} roadmap${task.current ? ", which is where you are now" : ""}`,
      level: `Week ${task.week}`,
      weight: task.current ? 2 : 0.8,
    });
  }

  for (const q of sources.dsa || []) {
    const pattern = clean(q.pattern);
    if (!pattern) continue;
    cards.push({
      id: `pattern:${q.id}`,
      kind: "pattern",
      topic: clean(q.topic) || "DSA",
      question: `${clean(q.title)} — which pattern solves this, and why?`,
      answer: pattern,
      points: clean(q.why_it_matters) ? [clean(q.why_it_matters)] : [],
      why: q.solved
        ? `You've solved this one — worth keeping the pattern fresh`
        : `${clean(q.difficulty)} · still unsolved on your DSA checklist`,
      link: q.neetcode_url,
      level: clean(q.difficulty) || undefined,
      weight: (q.solved ? 0.6 : 2.2) + (q.difficulty === "Hard" ? 0.3 : 0),
    });
  }

  return cards;
}

/* ---------------- Choosing today's session ---------------- */

export type SessionPlan = {
  queue: RevisionCard[];
  dueCount: number;
  newCount: number;
  heldBack: number;
};

export type PlanOptions = {
  /** Most cards in one sitting. A session has to end, or it's a chore with no finish line. */
  limit?: number;
  /** Most unseen cards in one sitting, so a first session isn't all strangers */
  newLimit?: number;
};

/**
 * Today's session: everything that has come round again, then a ration of new cards to fill
 * the rest. Due cards come first because forgetting is the thing worth catching.
 */
export function planSession(
  cards: RevisionCard[],
  progress: Record<string, CardProgress>,
  now: number,
  { limit = 20, newLimit = 8 }: PlanOptions = {}
): SessionPlan {
  const due = cards
    .filter((c) => isDue(progress[c.id], now))
    .sort((a, b) => (progress[a.id]?.dueAt ?? 0) - (progress[b.id]?.dueAt ?? 0));

  const fresh = cards
    .filter((c) => isNew(progress[c.id]))
    .sort((a, b) => b.weight - a.weight || a.id.localeCompare(b.id));

  const queue = due.slice(0, limit);
  const room = Math.max(0, Math.min(limit - queue.length, newLimit));
  queue.push(...fresh.slice(0, room));

  return {
    queue,
    dueCount: Math.min(due.length, limit),
    newCount: Math.min(fresh.length, room),
    heldBack: Math.max(0, due.length - limit),
  };
}

/** How the deck stands overall, for the numbers beside the title */
export function deckStanding(cards: RevisionCard[], progress: Record<string, CardProgress>, now: number) {
  let due = 0;
  let unseen = 0;
  let learned = 0;
  for (const card of cards) {
    const p = progress[card.id];
    if (isNew(p)) unseen += 1;
    else if (isDue(p, now)) due += 1;
    else if (p && p.box >= 3) learned += 1;
  }
  return { total: cards.length, due, unseen, learned };
}

/** The skills in a session and how many cards each has, most first — for the focus panel */
export function skillsInSession(queue: RevisionCard[]): { topic: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const card of queue) counts.set(card.topic, (counts.get(card.topic) ?? 0) + 1);
  return [...counts.entries()]
    .map(([topic, count]) => ({ topic, count }))
    .sort((a, b) => b.count - a.count || a.topic.localeCompare(b.topic));
}

/**
 * Where a missed card goes back into the queue: far enough that you've had to think again,
 * near enough that it's still the same sitting.
 */
export const REQUEUE_GAP = 4;

export function requeue(queue: RevisionCard[], card: RevisionCard, gap = REQUEUE_GAP): RevisionCard[] {
  const rest = queue.filter((c) => c.id !== card.id);
  const at = Math.min(gap, rest.length);
  return [...rest.slice(0, at), card, ...rest.slice(at)];
}
