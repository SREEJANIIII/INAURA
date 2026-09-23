/* eslint-disable react-hooks/set-state-in-effect */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, type AnalysisResult } from "../services/analysis";
import { getCapabilityMap, type SkillCapability } from "../services/capability";
import { getDsaChecklist, type DsaQuestion } from "../services/assessment";
import { roadmapPageData } from "../lib/pageData";
import type { RoadmapTask } from "../services/roadmap";
import "./Revision.css";

type Card = {
  id: string;
  kind: "skill" | "roadmap" | "dsa";
  label: string;
  title: string;
  prompt: string;
  answer: string;
  detail?: string;
  link?: string;
  solved?: boolean;
};

const pct = (value: number) => Math.round(value <= 1 ? value * 100 : value);

function skillCard(skill: SkillCapability): Card {
  const known = pct(skill.proficiency);
  const capability = skill.capabilities?.[0];
  return {
    id: `skill-${skill.slug}`,
    kind: "skill",
    label: `${known}% mastered`,
    title: skill.skill,
    prompt: `What should you be able to explain or do with ${skill.skill}?`,
    answer: capability?.summary || skill.explanation || `Review the core concepts and practical applications of ${skill.skill}.`,
    detail: capability?.observable_abilities?.slice(0, 3).join(" · "),
  };
}

function roadmapCard(task: RoadmapTask): Card {
  return {
    id: `roadmap-${task.id}`,
    kind: "roadmap",
    label: "From your roadmap",
    title: task.title,
    prompt: `How would you teach yourself: ${task.title}?`,
    answer: task.description || task.why_this_task || "Revisit this roadmap milestone and write down the key idea in your own words.",
    detail: task.skill_name,
    link: task.resources?.[0]?.url,
  };
}

function dsaCard(question: DsaQuestion, solved: boolean): Card {
  return {
    id: `dsa-${question.id}`,
    kind: "dsa",
    label: `${question.difficulty} · ${question.topic}`,
    title: question.title,
    prompt: `Before looking at a solution: which pattern would you use for ${question.title}?`,
    answer: `${question.pattern}. ${question.why_it_matters}`,
    detail: solved ? "Marked solved · keep it fresh" : "Not marked solved · practise this one",
    link: question.neetcode_url,
    solved,
  };
}

export default function Revision() {
  const [cards, setCards] = useState<Card[]>([]);
  const [index, setIndex] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [filter, setFilter] = useState<"all" | Card["kind"]>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [analysis, roadmapBundle, dsa] = await Promise.all([
        getLatestAnalysis().catch(() => null as AnalysisResult | null),
        roadmapPageData.fetch().catch(() => null),
        getDsaChecklist().catch(() => ({ questions: [], solved_ids: [] })),
      ]);
      const next: Card[] = [];
      if (analysis?.target_role) {
        const map = await getCapabilityMap({ target_role: analysis.target_role }).catch(() => null);
        (map?.skills || []).filter((skill) => pct(skill.proficiency) > 50).forEach((skill) => next.push(skillCard(skill)));
      }
      const tasks = roadmapBundle?.weeks.flatMap((week) => week.tasks || []) || [];
      const seen = new Set<string>();
      tasks.filter((task) => task.status !== "skipped").forEach((task) => {
        if (!seen.has(task.title)) { next.push(roadmapCard(task)); seen.add(task.title); }
      });
      const solved = new Set(dsa.solved_ids || []);
      dsa.questions.forEach((question) => next.push(dsaCard(question, solved.has(question.id))));
      setCards(next);
      setIndex(0);
      setShowAnswer(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Revision cards could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visibleCards = useMemo(() => filter === "all" ? cards : cards.filter((card) => card.kind === filter), [cards, filter]);
  const move = (step: number) => {
    if (!visibleCards.length) return;
    setIndex((current) => (current + step + visibleCards.length) % visibleCards.length);
    setShowAnswer(false);
  };

  const safeIndex = visibleCards.length ? Math.min(index, visibleCards.length - 1) : 0;
  const activeCard = visibleCards[safeIndex];

  return (
    <main className="revision-page">
      <header className="revision-head">
        <div>
          <p className="revision-kicker">STAY SHARP</p>
          <h1>Revision</h1>
          <p>Turn what you’re learning into quick recall. Your cards come from your roadmap, proven skills, and DSA practice.</p>
        </div>
        <button className="revision-refresh" type="button" onClick={() => void load()} disabled={loading}>↻ Refresh cards</button>
      </header>

      <div className="revision-tabs" role="tablist" aria-label="Revision card type">
        {([['all', 'All cards'], ['skill', 'Skills > 50%'], ['roadmap', 'Roadmap'], ['dsa', 'DSA']] as const).map(([value, label]) => (
          <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? "is-active" : ""} onClick={() => { setFilter(value); setIndex(0); setShowAnswer(false); }}>{label}</button>
        ))}
      </div>

      {error && <div className="revision-alert">{error}</div>}
      {loading ? <div className="revision-empty">Building your revision deck…</div> : !activeCard ? (
        <div className="revision-empty"><h2>No cards yet</h2><p>Complete an analysis or add roadmap/DSA progress to build your personalized deck.</p><Link to="/roadmap">Open your roadmap →</Link></div>
      ) : (
        <section className="revision-study" aria-live="polite">
          <div className="revision-progress"><span>{safeIndex + 1} / {visibleCards.length}</span><span>{activeCard.label}</span></div>
          <button type="button" className={`revision-card ${showAnswer ? "is-flipped" : ""}`} onClick={() => setShowAnswer((value) => !value)} aria-label={showAnswer ? "Hide answer" : "Reveal answer"}>
            <span className="revision-card__type">{activeCard.kind === "dsa" ? "DSA FLASHCARD" : activeCard.kind === "roadmap" ? "ROADMAP FLASHCARD" : "SKILL FLASHCARD"}</span>
            <span className="revision-card__title">{activeCard.title}</span>
            {!showAnswer ? <><span className="revision-card__prompt">{activeCard.prompt}</span><span className="revision-card__hint">Tap to reveal answer</span></> : <><span className="revision-card__answer">{activeCard.answer}</span>{activeCard.detail && <span className="revision-card__detail">{activeCard.detail}</span>}{activeCard.link && <a href={activeCard.link} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>Open practice resource ↗</a>}</>}
          </button>
          <div className="revision-controls"><button type="button" onClick={() => move(-1)}>← Previous</button><button type="button" className="revision-next" onClick={() => move(1)}>Next card →</button></div>
        </section>
      )}
    </main>
  );
}
