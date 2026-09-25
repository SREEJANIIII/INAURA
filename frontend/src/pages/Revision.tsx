import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import StackedDeck, { type DeckDirection } from "@/components/ui/stacked-deck";
import {
  analysisStateData,
  capabilityMapData,
  dsaChecklistData,
  evidencePageData,
  roadmapPageData,
  subscribePageData,
} from "../lib/pageData";
import {
  buildDeck,
  deckStanding,
  KIND_LABEL,
  planSession,
  requeue,
  skillsInSession,
  type RevisionCard,
} from "../lib/revision/deck";
import {
  grade,
  newProgress,
  streakFrom,
  whenBack,
  type Answer,
  type CardProgress,
} from "../lib/revision/schedule";
import { loadProgress, loadStudyDays, recordStudyDay, saveProgress } from "../lib/revision/store";
import "./Revision.css";

type Answered = { card: RevisionCard; answer: Answer; firstTry: boolean };

/** The moment a button was pressed. Only ever called from an event, never during a render. */
const pressedAt = () => Date.now();

/** Throwing a card left, down or right is the same as pressing the button underneath it */
const BY_DIRECTION: Record<DeckDirection, Answer> = { left: "again", down: "almost", right: "got" };

/**
 * Revision reads the same remembered copies every other page uses, rather than fetching its
 * own. The capability map in particular is the slowest thing INAURA asks for, and Career
 * Track has usually already warmed it — so this page opens on what's there and fills in the
 * rest as it arrives, instead of showing a spinner while it asks all over again.
 */
export default function Revision() {
  const [progress, setProgress] = useState<Record<string, CardProgress>>(() => loadProgress());
  const [days, setDays] = useState<string[]>(() => loadStudyDays());
  /** Read when something happens rather than on every render, so rendering stays pure */
  const [now, setNow] = useState(() => Date.now());

  const [queue, setQueue] = useState<RevisionCard[]>([]);
  const [showAnswer, setShowAnswer] = useState(false);
  const [answered, setAnswered] = useState<Answered[]>([]);
  const [started, setStarted] = useState(false);
  const [planned, setPlanned] = useState(0);
  /** Cards missed this session, so a card only counts as learned if it was right first time */
  const missed = useRef<Set<string>>(new Set());

  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const roadmap = useSyncExternalStore(subscribePageData, roadmapPageData.peek);
  const dsa = useSyncExternalStore(subscribePageData, dsaChecklistData.peek);

  const role = (analysisState ?? evidence?.analysisState)?.target_role ?? null;
  const mapEntry = role ? capabilityMapData(role) : null;
  const map = useSyncExternalStore(subscribePageData, () => mapEntry?.peek());

  // Whether the first round of asking has finished, either way. Tracked so a failed fetch
  // or an account with nothing in it ends on an answer rather than a spinner forever.
  const [asked, setAsked] = useState(false);
  const [mapAsked, setMapAsked] = useState(false);

  useEffect(() => {
    let alive = true;
    void Promise.allSettled([
      analysisStateData.fetch(),
      roadmapPageData.fetch(),
      dsaChecklistData.fetch(),
    ]).then(() => {
      if (alive) setAsked(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!mapEntry) return;
    let alive = true;
    void mapEntry
      .fetch()
      .catch(() => undefined)
      .finally(() => {
        if (alive) setMapAsked(true);
      });
    return () => {
      alive = false;
    };
  }, [mapEntry]);

  const cards = useMemo(() => {
    const tasks = (roadmap?.weeks || []).flatMap((w) =>
      (w.tasks || [])
        .filter((t) => t.status !== "completed" && t.status !== "skipped")
        .map((t) => ({
          id: t.id,
          title: t.title,
          description: t.description,
          skill_name: t.skill_name,
          week: w.week_number,
          current: w.status === "current" || w.status === "behind_schedule",
        }))
    );
    const solved = new Set(dsa?.solved_ids || []);
    return buildDeck({
      role,
      skills: map?.skills,
      tasks,
      dsa: (dsa?.questions || []).map((q) => ({
        id: q.id,
        title: q.title,
        topic: q.topic,
        pattern: q.pattern,
        difficulty: q.difficulty,
        why_it_matters: q.why_it_matters,
        neetcode_url: q.neetcode_url,
        solved: solved.has(q.id),
      })),
    });
  }, [map, roadmap, dsa, role]);

  const standing = useMemo(() => deckStanding(cards, progress, now), [cards, progress, now]);
  const plan = useMemo(() => planSession(cards, progress, now), [cards, progress, now]);
  const streak = useMemo(() => streakFrom(days, now), [days, now]);
  const focus = useMemo(() => skillsInSession(started ? queue : plan.queue), [started, queue, plan.queue]);

  const card = queue[0];
  const done = started && !card;
  const waiting = !asked || (!!role && !mapAsked && cards.length === 0);

  const begin = () => {
    const at = pressedAt();
    setNow(at);
    missed.current = new Set();
    setQueue(plan.queue);
    setPlanned(plan.queue.length);
    setAnswered([]);
    setShowAnswer(false);
    setStarted(true);
    setDays(recordStudyDay(at));
  };

  const answer = (choice: Answer) => {
    if (!card) return;
    const at = pressedAt();
    setNow(at);
    const next = { ...progress, [card.id]: grade(progress[card.id] ?? newProgress(), choice, at) };
    setProgress(next);
    saveProgress(next);

    if (choice === "again") missed.current.add(card.id);
    setAnswered((list) => [
      ...list,
      { card, answer: choice, firstTry: choice === "got" && !missed.current.has(card.id) },
    ]);
    // A card you didn't have comes back before the sitting ends, not in three days
    setQueue((q) => (choice === "again" ? requeue(q, card) : q.slice(1)));
    setShowAnswer(false);
  };

  const firstTry = answered.filter((a) => a.firstTry).length;
  const seenCount = new Set(answered.map((a) => a.card.id)).size;

  /* ---------------- Before there is anything to show ---------------- */

  if (waiting) {
    return (
      <main className="rev">
        <div className="rev__wait">Building today's session…</div>
      </main>
    );
  }

  if (!cards.length) {
    return (
      <main className="rev">
        <div className="rev__wait rev__wait--empty">
          <h1>Nothing to revise yet</h1>
          <p>
            Cards come from the skills your analysis knows about, the gaps it found, and the DSA you're
            practising. Add your evidence and the deck writes itself.
          </p>
          <Link to="/analysis" className="rev__cta">
            Add your evidence
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="rev">
      <header className="rev__head">
        <div className="rev__title">
          <h1>Revision</h1>
          <p>Your daily career skill workout.</p>
        </div>
        <p className="rev__stats">
          <span>
            <strong>{standing.due}</strong> due
          </span>
          <span>
            <strong>{streak}</strong> day{streak === 1 ? "" : "s"} streak
          </span>
          <span>
            <strong>{standing.learned}</strong>/{standing.total} known
          </span>
        </p>
      </header>

      <div className="rev__stage">
        {!started ? (
          <div className="rev-open">
            <p className="rev-open__lead">
              {plan.queue.length > 0 ? (
                <>
                  <strong>{plan.queue.length}</strong> cards are waiting
                </>
              ) : (
                "You're up to date"
              )}
            </p>
            <p className="rev-open__mix">
              {plan.queue.length > 0
                ? [
                    plan.dueCount > 0 && `${plan.dueCount} come round again`,
                    plan.newCount > 0 && `${plan.newCount} you haven't met`,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : "Nothing has fallen due. Come back tomorrow, or keep going on your roadmap."}
            </p>
            {plan.queue.length > 0 && (
              <button type="button" className="rev__cta" onClick={begin}>
                Start today's session
              </button>
            )}
            {plan.heldBack > 0 && <p className="rev-open__held">{plan.heldBack} more wait for the next sitting.</p>}
          </div>
        ) : done ? (
          <div className="rev-open">
            <p className="rev-open__lead">
              <strong>{firstTry}</strong> of {seenCount} right first time
            </p>
            <p className="rev-open__mix">
              That's today's session finished. Each card you knew has gone away for longer; the ones you
              didn't will be back sooner.
            </p>
            <div className="rev-open__row">
              <button type="button" className="rev__cta" onClick={() => setStarted(false)}>
                Done
              </button>
              {plan.queue.length > 0 && (
                <button type="button" className="rev__ghost" onClick={begin}>
                  Another {Math.min(plan.queue.length, 20)}
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <StackedDeck
              className="rev-deck"
              cardClassName="rev-card"
              items={queue}
              getKey={(c) => c.id}
              revealed={showAnswer}
              onReveal={() => setShowAnswer(true)}
              onAnswer={(dir) => answer(BY_DIRECTION[dir])}
              label="Revision cards — enter to reveal, then the arrow keys or a swipe to answer"
              renderCard={(c, state) => (
                <>
                  <header className="rev-card__top">
                    <span className={`rev-card__kind rev-card__kind--${c.kind}`}>{KIND_LABEL[c.kind]}</span>
                    {c.level && <span className="rev-card__level">{c.level}</span>}
                  </header>

                  <h2 className="rev-card__skill">{c.topic}</h2>
                  <p className="rev-card__q">{c.question}</p>

                  {state.revealed ? (
                    <div className="rev-card__answer">
                      <p className="rev-card__a-lead">{c.answer}</p>
                      {c.points.length > 0 && (
                        <ul className="rev-card__points">
                          {c.points.map((point, i) => (
                            <li key={i}>{point}</li>
                          ))}
                        </ul>
                      )}
                      {c.link && (
                        <a
                          href={c.link}
                          target="_blank"
                          rel="noreferrer"
                          className="rev-card__link"
                          onClick={(e) => e.stopPropagation()}
                        >
                          Practise it
                        </a>
                      )}
                    </div>
                  ) : (
                    <p className="rev-card__why">
                      <span>Why you're seeing this</span>
                      {c.why}
                    </p>
                  )}
                </>
              )}
            />

            <div className="rev-act">
              {showAnswer ? (
                <div className="rev-grade">
                  {(
                    [
                      ["again", "Didn't know"],
                      ["almost", "Almost"],
                      ["got", "Got it"],
                    ] as const
                  ).map(([value, text]) => (
                    <button
                      key={value}
                      type="button"
                      className={`rev-grade__btn rev-grade__btn--${value}`}
                      onClick={() => answer(value)}
                    >
                      {text}
                      <em>
                        {value === "again"
                          ? "back shortly"
                          : whenBack(grade(progress[card.id] ?? newProgress(), value, now), now)}
                      </em>
                    </button>
                  ))}
                </div>
              ) : (
                <button type="button" className="rev-reveal" onClick={() => setShowAnswer(true)}>
                  Show answer
                </button>
              )}
              <p className="rev-act__hint">
                {showAnswer
                  ? "Swipe the card, or use the arrow keys"
                  : `${seenCount + 1} of ${planned} · tap the card or press enter`}
              </p>
            </div>
          </>
        )}
      </div>

      {focus.length > 0 && (
        <footer className="rev-focus">
          <h2>Today's focus</h2>
          <ul>
            {focus.slice(0, 6).map((s) => (
              <li key={s.topic}>
                {s.topic}
                <em>{s.count}</em>
              </li>
            ))}
            {focus.length > 6 && <li className="rev-focus__more">+{focus.length - 6} more</li>}
          </ul>
          <Link to="/career-track">Career track</Link>
        </footer>
      )}

      <p className="rev-live" aria-live="polite">
        {card ? (showAnswer ? `Answer: ${card.answer}. ${card.points.join(". ")}` : card.question) : ""}
      </p>
    </main>
  );
}
