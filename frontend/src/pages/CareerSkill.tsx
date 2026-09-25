import { useEffect, useMemo, useState, useSyncExternalStore, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import AssessmentModal from "../components/assessment/AssessmentModal";
import type { AvailableAssessment } from "../services/assessment";
import {
  capabilityMapData,
  resultsPageData,
  roadmapPageData,
  roleCatalogData,
  subscribePageData,
} from "../lib/pageData";
import {
  STATUS_LABEL,
  assessmentFor,
  buildTrack,
  findRole,
  phaseFor,
  type TrackSkill,
} from "../components/career-track/careerTrackModel";
import { useInViewOnce } from "../components/career-track/motion";
import { ProgressBar, ProgressRing, SkillMark } from "../components/career-track/Progress";
import TransitionLink from "../components/career-track/TransitionLink";
import "../components/career-track/CareerTrack.css";
import Button from "@/components/ui/app-button";

export default function CareerSkill() {
  const { careerId, skillId } = useParams();
  const catalog = useSyncExternalStore(subscribePageData, roleCatalogData.peek);
  const results = useSyncExternalStore(subscribePageData, resultsPageData.peek);
  const roadmap = useSyncExternalStore(subscribePageData, roadmapPageData.peek);
  const role = catalog ? findRole(catalog, careerId) : undefined;
  const mapEntry = role ? capabilityMapData(role.title) : null;
  const map = useSyncExternalStore(subscribePageData, () => mapEntry?.peek());

  const [error, setError] = useState<string | null>(null);
  const [assessing, setAssessing] = useState<AvailableAssessment | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // A new skill page starts at the top, not wherever the previous page was scrolled to
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [careerId, skillId]);

  useEffect(() => {
    roleCatalogData.fetch().catch(() => setError("This skill couldn’t be loaded. Check your connection and try again."));
    resultsPageData.fetch().catch(() => undefined);
    roadmapPageData.fetch().catch(() => undefined);
  }, []);

  useEffect(() => {
    mapEntry?.fetch().catch(() => setError("This skill couldn’t be loaded. Check your connection and try again."));
  }, [mapEntry]);

  const track = useMemo(() => (role && map ? buildTrack({ role, map, analysis: results?.analysis }) : null), [role, map, results]);
  const skill = track?.skills.find((s) => s.id === skillId);

  // After an assessment, refresh the numbers in place — no page reload
  const refreshAfterAssessment = async () => {
    if (!role) return;
    setRefreshing(true);
    try {
      await Promise.all([capabilityMapData(role.title).fetch(true), resultsPageData.fetch(true)]);
    } catch {
      setError("Your result was saved, but the updated progress couldn’t be loaded yet. Refresh in a moment.");
    } finally {
      setRefreshing(false);
    }
  };

  if (error && !skill) {
    return (
      <div className="ct">
        <div className="ct__inner">
          <section className="ct-state">
            <h1 className="ct-state__title">Skill unavailable</h1>
            <p>{error}</p>
            <Button asChild variant="primary"><Link to={careerId ? `/career-track/${careerId}` : "/career-track"}>Back to career track</Link></Button>
          </section>
        </div>
      </div>
    );
  }

  if (!track || !role) {
    return (
      <div className="ct">
        <div className="ct__inner" aria-busy="true">
          <div className="ct-skel ct-skel--title" />
          <div className="ct-skel ct-skel--ready" />
        </div>
      </div>
    );
  }

  if (!skill) {
    return (
      <div className="ct">
        <div className="ct__inner">
          <section className="ct-state">
            <h1 className="ct-state__title">{role.title} doesn’t include that skill</h1>
            <p>Open the career track to see every skill this role requires.</p>
            <Button asChild variant="primary"><TransitionLink to={`/career-track/${track.id}`}>Back to {role.title}</TransitionLink></Button>
          </section>
        </div>
      </div>
    );
  }

  const assessment = assessmentFor(skill, results?.assessable ?? []);
  const roadmapTask = (roadmap?.weeks ?? [])
    .flatMap((w) => (w.tasks ?? []).map((t) => ({ week: w, task: t })))
    .find(({ task }) => task.status !== "completed" && [task.skill_slug, task.skill_name].some((k) => k && k.toLowerCase().replace(/[^a-z0-9]+/g, "_") === skill.slug));

  return (
    <div className="ct ct--skill">
      <div className="ct__inner">
        <nav className="ct-crumbs" aria-label="Breadcrumb">
          <TransitionLink to={`/career-track/${track.id}`}>Career Track</TransitionLink>
          <span aria-hidden="true">/</span>
          <TransitionLink to={`/career-track/${track.id}`}>{track.title}</TransitionLink>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{skill.name}</span>
        </nav>

        <SkillHero skill={skill} refreshing={refreshing} />

        {skill.status === "completed" && <CompletionNote skill={skill} />}

        <div className="ct-actions ct-rise" style={{ "--d": 3 } as CSSProperties}>
          {roadmapTask ? (
            <Button asChild variant="primary" className="ib--stacked">
              <Link to="/roadmap">
                Continue learning
                <span className="ct-btn__sub">Week {roadmapTask.week.week_number}: {roadmapTask.task.title}</span>
              </Link>
            </Button>
          ) : (
            <Button asChild variant="primary">
              <a
                href="#learn"
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById("learn")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                {skill.status === "not-started" ? "Start learning" : skill.status === "completed" ? "Keep improving" : "Continue learning"}
              </a>
            </Button>
          )}
          <Button asChild variant="secondary"><Link to="/interview">Practice in a mock interview</Link></Button>
          {assessment ? (
            <Button variant="secondary" onClick={() => setAssessing(assessment)}>
              {assessment.last_assessment ? "Retake skill assessment" : "Take skill assessment"}
            </Button>
          ) : (
            <span className="ct-btn ct-btn--disabled" title="INAURA doesn’t have an assessment for this skill yet">
              No assessment for this skill yet
            </span>
          )}
        </div>

        {skill.prerequisites.length > 0 && (
          <section className="ct-sec ct-sec--tight" aria-labelledby="ct-prereq">
            <h2 id="ct-prereq" className="ct-h3">Builds on</h2>
            <ul className="ct-prereqs">
              {skill.prerequisites.map((p) => (
                <li key={p.id}>
                  <TransitionLink to={`/career-track/${track.id}/${p.id}`} className={`ct-chip ct-chip--${p.met ? "completed" : "in-progress"}`}>
                    {p.met ? "✓ " : ""}
                    {p.name}
                    {!p.met && <span className="ct-chip__pct">not yet at required level</span>}
                  </TransitionLink>
                </li>
              ))}
            </ul>
            {skill.status === "locked" && (
              <p className="ct-muted">This skill unlocks once you reach the required level in the skills above.</p>
            )}
          </section>
        )}

        <div className="ct-split">
          <GapBlock skill={skill} />
          <Stats skill={skill} assessment={assessment} />
        </div>

        <Topics skill={skill} />

        <section id="learn" className="ct-sec" aria-labelledby="ct-learn">
          <div className="ct-sec__head">
            <h2 id="ct-learn">What to learn next</h2>
            <p>Next steps and resources INAURA recommends for the {skill.name} topics you haven’t shown yet.</p>
          </div>
          {skill.nextActions.length === 0 && skill.resources.length === 0 ? (
            <p className="ct-empty">
              {skill.status === "completed"
                ? "You’ve shown every topic INAURA checks for this skill."
                : "INAURA doesn’t have learning steps for this skill yet."}
            </p>
          ) : (
            <div className="ct-learn">
              {skill.nextActions.length > 0 && (
                <ol className="ct-steps">
                  {skill.nextActions.map((a, i) => (
                    <li key={i} className="ct-rise" style={{ "--d": i } as CSSProperties}>
                      <span className="ct-steps__n ct-num">{i + 1}</span>
                      <span>{a}</span>
                    </li>
                  ))}
                </ol>
              )}
              {skill.resources.length > 0 && (
                <ul className="ct-resources">
                  {skill.resources.map((r) => (
                    <li key={r.url}>
                      <a href={r.url} target="_blank" rel="noreferrer" className="ct-resource">
                        <span className="ct-resource__title">{r.title}</span>
                        <span className="ct-resource__provider">{r.provider}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>

      {assessing && (
        <AssessmentModal
          key={assessing.skill}
          skill={assessing.skill}
          evidenceProficiency={assessing.proficiency}
          evidenceConfidence={assessing.confidence}
          onClose={() => setAssessing(null)}
          onCompleted={() => {
            void refreshAfterAssessment();
          }}
        />
      )}
    </div>
  );
}

function SkillHero({ skill, refreshing }: { skill: TrackSkill; refreshing: boolean }) {
  const phase = phaseFor(skill.category).id;
  return (
    <header className="ct-hero">
      <div className="ct-hero__text">
        <span className="ct-hero__mark" style={{ viewTransitionName: "ct-skill-mark" }}>
          <SkillMark name={skill.name} phase={phase} size="lg" />
        </span>
        <div>
          <p className={`ct-status ct-status--${skill.status}`}>{STATUS_LABEL[skill.status]}</p>
          <h1 className="ct-title">{skill.name}</h1>
          <p className="ct-hero__levels">
            <span>{skill.currentLevel}</span>
            <svg width="18" height="10" viewBox="0 0 18 10" aria-label="to">
              <path d="M1 5h15M12.5 1.5 16 5l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>{skill.requiredLevel}</span>
          </p>
          {skill.description && <p className="ct-lead">{skill.description}</p>}
          {refreshing && <p className="ct-muted">Updating your progress…</p>}
        </div>
      </div>
      <ProgressRing value={skill.currentProgress} target={skill.requiredProgress} tone={skill.status === "completed" ? "done" : "accent"}>
        <span className="ct-ring__label">complete</span>
      </ProgressRing>
    </header>
  );
}

function CompletionNote({ skill }: { skill: TrackSkill }) {
  return (
    <div className="ct-complete" role="status">
      <span className="ct-complete__badge" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24">
          <circle className="ct-complete__circle" cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path className="ct-complete__tick" d="M7.5 12.4 10.5 15.3 16.5 9" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <div>
        <p className="ct-complete__title">{skill.name} is at the required level</p>
        <p className="ct-muted">Your evidence meets what {skill.raw.role || "this role"} asks for. Keep it current with new projects or an assessment.</p>
      </div>
    </div>
  );
}

function GapBlock({ skill }: { skill: TrackSkill }) {
  const [ref, inView] = useInViewOnce<HTMLElement>();
  return (
    <section ref={ref} className={`ct-panel ct-gapblock${inView ? " is-in" : ""}`} aria-labelledby="ct-gap">
      <h2 id="ct-gap" className="ct-h3">Skill gap</h2>
      <div className="ct-gapblock__rows">
        <div className="ct-gapblock__row">
          <span>You</span>
          <ProgressBar value={skill.currentProgress} tone={skill.status === "completed" ? "done" : "accent"} label="Your level" />
          <strong className="ct-num">{skill.currentProgress}%</strong>
        </div>
        <div className="ct-gapblock__row">
          <span>Required</span>
          <ProgressBar value={skill.requiredProgress} tone="muted" label="Required level" />
          <strong className="ct-num">{skill.requiredProgress}%</strong>
        </div>
      </div>
      <dl className="ct-gapblock__facts">
        <div>
          <dt>Current level</dt>
          <dd>{skill.currentLevel}</dd>
        </div>
        <div>
          <dt>Target level</dt>
          <dd>{skill.requiredLevel}</dd>
        </div>
        <div>
          <dt>Gap</dt>
          <dd className={skill.gap > 0 ? "ct-gap" : "ct-gap ct-gap--none"}>{skill.gap > 0 ? `${skill.gap}%` : "None"}</dd>
        </div>
      </dl>
    </section>
  );
}

function Stats({ skill, assessment }: { skill: TrackSkill; assessment?: AvailableAssessment }) {
  const last = assessment?.last_assessment;
  const stats = [
    { label: "Topics shown", value: skill.totalTopics ? `${skill.completedTopics} / ${skill.totalTopics}` : "—" },
    { label: "Evidence confidence", value: `${skill.confidence}%` },
    {
      label: "Assessment accuracy",
      value: last && last.question_count ? `${Math.round((last.correct_count / last.question_count) * 100)}%` : "Not taken",
    },
    { label: "Questions answered", value: last ? String(last.question_count) : "0" },
    { label: "Evidence sources", value: String(skill.evidenceCount) },
    { label: "Importance for role", value: `${skill.importance}%` },
  ];
  return (
    <section className="ct-stats" aria-label={`${skill.name} statistics`}>
      {stats.map((s, i) => (
        <div key={s.label} className="ct-stat ct-rise" style={{ "--d": i } as CSSProperties}>
          <span className="ct-stat__label">{s.label}</span>
          <span className="ct-stat__value ct-num">{s.value}</span>
        </div>
      ))}
    </section>
  );
}

function Topics({ skill }: { skill: TrackSkill }) {
  const [ref, inView] = useInViewOnce<HTMLElement>();
  if (skill.totalTopics === 0) {
    return (
      <section className="ct-sec" aria-labelledby="ct-topics">
        <div className="ct-sec__head">
          <h2 id="ct-topics">Topics</h2>
        </div>
        <p className="ct-empty">INAURA doesn’t have a topic breakdown for {skill.name} yet, so progress is based on your overall evidence.</p>
      </section>
    );
  }
  const order = { done: 0, developing: 1, todo: 2 } as const;
  const topics = [...skill.topics].sort((a, b) => order[a.state] - order[b.state]);
  return (
    <section ref={ref} className={`ct-sec${inView ? " is-in" : ""}`} aria-labelledby="ct-topics">
      <div className="ct-sec__head ct-sec__head--row">
        <div>
          <h2 id="ct-topics">Topics</h2>
          <p>What INAURA expects you to be able to do with {skill.name}, and what your evidence already shows.</p>
        </div>
        <span className="ct-topics__count ct-num">
          {skill.completedTopics} / {skill.totalTopics} shown
        </span>
      </div>
      <ul className="ct-topics">
        {topics.map((t, i) => (
          <li key={t.id} className={`ct-topic ct-topic--${t.state}`} style={{ "--d": i } as CSSProperties}>
            <span className="ct-topic__mark" aria-hidden="true">
              {t.state === "done" ? (
                <svg width="14" height="14" viewBox="0 0 12 12">
                  <path className="ct-topic__tick" d="M2.5 6.4 5 8.8l4.5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : t.state === "developing" ? (
                <span className="ct-topic__half" />
              ) : null}
            </span>
            <span className="ct-topic__text">
              <span className="ct-topic__title">{t.title}</span>
              {t.summary && <span className="ct-topic__summary">{t.summary}</span>}
            </span>
            <span className="ct-topic__state">
              {t.state === "done" ? "Shown" : t.state === "developing" ? "Partly shown" : "Not shown yet"}
            </span>
          </li>
        ))}
      </ul>
      {skill.completedTopics < skill.totalTopics && (
        <a
          href="#learn"
          className="ct-link"
          onClick={(e) => {
            e.preventDefault();
            document.getElementById("learn")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          See how to show the remaining topics
        </a>
      )}
    </section>
  );
}
