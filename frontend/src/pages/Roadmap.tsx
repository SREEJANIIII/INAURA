/* eslint-disable react-hooks/set-state-in-effect */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { type AnalysisResult, type SkillGap } from "../services/analysis";
import { type Profile } from "../services/profile";
import {
  generateRoadmap,
  getLatestRoadmap,
  reassessRoadmap,
  updateRoadmapTask,
  type Roadmap,
  type RoadmapTask,
  type RoadmapWeek,
} from "../services/roadmap";
import { resultsPageData, roadmapPageData } from "../lib/pageData";
import { getRoleSync, resetRoleSync, subscribeRoleSync } from "../lib/roleSync";
import { friendlyError } from "../lib/errors";
import { useDialog } from "../lib/useDialog";
import Button from "@/components/ui/app-button";
import AssessmentModal from "../components/assessment/AssessmentModal";
import type { SubmitAssessmentResponse } from "../services/assessment";
import JourneyMap from "../components/roadmap/JourneyMap";
import StageSheet from "../components/roadmap/StageSheet";
import MoveProjection from "../components/roadmap/MoveProjection";
import WeekPlan, { PASS_SCORE, type TaskUpdate } from "../components/roadmap/WeekPlan";
import StateGlyph from "../components/roadmap/StateGlyph";
import { useMedia } from "../components/roadmap/hooks";
import {
  STATE_META,
  STATE_ORDER,
  buildHorizon,
  buildJourney,
  isCleared,
  readableHours,
  readinessModel,
  type JourneySkill,
} from "../components/roadmap/journeyModel";

type RoadmapPageData = NonNullable<ReturnType<typeof roadmapPageData.peek>>;
import "./Roadmap.css";
import "../components/roadmap/Journey.css";

function formatDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const passed = (result: SubmitAssessmentResponse) =>
  result.score >= PASS_SCORE && result.counts_as_evidence !== false && result.validity !== "invalid";

/** A saved task put back into its week, with the week's completion worked out again */
function withTask(weeks: RoadmapWeek[], task: RoadmapTask, updated: RoadmapTask) {
  return weeks.map((week) => {
    if (week.id !== task.roadmap_week_id) return week;
    const updatedTasks = (week.tasks ?? []).map((item) => (item.id === task.id ? updated : item));
    const completion = updatedTasks.length
      ? updatedTasks.reduce((total, item) => total + item.completion_percentage, 0) / updatedTasks.length
      : 0;
    return {
      ...week,
      tasks: updatedTasks,
      completion_percentage: completion,
      status: (completion >= 100 ? "completed" : week.status === "locked" ? "locked" : "current") as RoadmapWeek["status"],
    };
  });
}

export default function Roadmap() {
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [weeks, setWeeks] = useState<RoadmapWeek[]>([]);
  const [selectedWeekNum, setSelectedWeekNum] = useState(1);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [gaps, setGaps] = useState<SkillGap[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(() => !roadmapPageData.peek());
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [showAdaptiveNotice, setShowAdaptiveNotice] = useState(false);
  const [assessingTarget, setAssessingTarget] = useState<{ skillName: string; task: RoadmapTask } | null>(null);
  const [assessNote, setAssessNote] = useState<string | null>(null);
  const [selectedStage, setSelectedStage] = useState<number | null>(null);
  const [openSkill, setOpenSkill] = useState<string | null>(null);
  const weekRef = useRef<HTMLDivElement>(null);
  const phone = useMedia("(max-width: 640px)");
  // Rebuilding throws away the current plan and every task ticked on it, so it asks first
  const [confirmRebuild, setConfirmRebuild] = useState(false);
  const rebuildRef = useDialog<HTMLDivElement>(confirmRebuild, () => setConfirmRebuild(false));

  const applyData = useCallback((data: RoadmapPageData) => {
    setProfile(data.profile);
    setAnalysis(data.analysis);
    setGaps(data.gaps ?? []);
    setRoadmap(data.roadmap);
    setWeeks(data.weeks);
    if (data.roadmap) {
      const preferredWeek =
        data.weeks.find((week) => (week.tasks ?? []).some((t) => !isCleared(t)))?.week_number ||
        data.roadmap.current_week_index ||
        data.weeks[0]?.week_number ||
        1;
      setSelectedWeekNum(preferredWeek);
    }
  }, []);

  const loadAll = useCallback(async (force = true) => {
    // Only show the full-page loader when there's nothing on screen yet
    if (!roadmapPageData.peek()) setLoading(true);
    setError(null);
    try {
      applyData(await roadmapPageData.fetch(force));
    } catch (loadError) {
      // A failed background refresh keeps the last-seen roadmap on screen
      if (!force && roadmapPageData.peek()) return;
      setError(friendlyError(loadError, "Your roadmap couldn’t be loaded. Check your connection and try again."));
    } finally {
      setLoading(false);
    }
  }, [applyData]);

  // Show last-seen data before the first paint, then refresh in the background
  useLayoutEffect(() => {
    const cachedData = roadmapPageData.peek();
    if (cachedData) applyData(cachedData);
    void loadAll(false);
  }, [applyData, loadAll]);

  // A career change rebuilds the plan in the background; show the new one as soon as it lands
  const roleSync = useSyncExternalStore(subscribeRoleSync, getRoleSync);
  const rebuilding = roleSync.stage === "analysing" || roleSync.stage === "building";
  useEffect(() => {
    if (roleSync.stage !== "done") return;
    const rebuilt = roadmapPageData.peek();
    if (rebuilt) applyData(rebuilt);
  }, [roleSync.stage, applyData]);

  const role = roadmap?.target_role || analysis?.target_role || "your target role";
  const journey = useMemo(() => buildJourney({ weeks, roadmap, gaps }), [weeks, roadmap, gaps]);
  const horizon = useMemo(() => buildHorizon(role, analysis, gaps, weeks), [role, analysis, gaps, weeks]);
  const model = useMemo(() => readinessModel(role, analysis, gaps), [role, analysis, gaps]);

  // A checkpoint that no longer exists (the plan was rebuilt) closes its detail
  useEffect(() => {
    if (selectedStage !== null && selectedStage >= journey.stages.length) {
      setSelectedStage(null);
      setOpenSkill(null);
    }
  }, [journey.stages.length, selectedStage]);

  const handleGenerate = async () => {
    setConfirmRebuild(false);
    if (!profile?.hours_per_week) {
      setError("Set how many hours a week you can study in your profile, so the plan fits your time.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const generated = await generateRoadmap(analysis?.target_role, profile.hours_per_week);
      setRoadmap(generated);
      if (generated.weeks?.length) {
        setWeeks(generated.weeks);
        setSelectedWeekNum(generated.current_week_index || generated.weeks[0].week_number);
      }
      setSelectedStage(null);
      setOpenSkill(null);
      await loadAll();
    } catch (generateError) {
      setError(friendlyError(generateError, "Your roadmap couldn’t be built. Try again in a moment."));
    } finally {
      setGenerating(false);
    }
  };

  const handleAdaptiveReassess = async () => {
    if (!roadmap) return;
    setReassessing(true);
    setError(null);
    try {
      await reassessRoadmap({
        target_role: roadmap.target_role,
        adjust_hours_per_week: profile?.hours_per_week,
        mode: "compress",
      });
      setShowAdaptiveNotice(true);
      await loadAll();
    } catch (reassessError) {
      setError(friendlyError(reassessError, "Your schedule couldn’t be adjusted. Try again in a moment."));
    } finally {
      setReassessing(false);
    }
  };

  /** Save one task; returns whether it saved */
  const saveTask = async (task: RoadmapTask, patch: TaskUpdate) => {
    setUpdating(task.id);
    setError(null);
    try {
      const updated = await updateRoadmapTask(task.id, patch);
      setWeeks((current) => withTask(current, task, updated));
      return true;
    } catch (updateError) {
      setError(friendlyError(updateError, "That task couldn’t be updated. Check your connection and try again."));
      return false;
    } finally {
      setUpdating(null);
    }
  };

  /** After saving: the server may have moved you to the next week, and other pages should see the change */
  const refreshAfterSave = async () => {
    const latest = await getLatestRoadmap().catch(() => null);
    if (latest) setRoadmap(latest);
    // Refresh the remembered copy so reopening Roadmap shows this change
    roadmapPageData.fetch(true).catch(() => undefined);
  };

  const handleUpdateTask = async (task: RoadmapTask, patch: TaskUpdate) => {
    if (await saveTask(task, patch)) await refreshAfterSave();
  };

  // Unticking means "not done after all": back to the start, not left at 99%
  const toggleTask = (task: RoadmapTask, done: boolean) =>
    handleUpdateTask(task, done ? { status: "completed", completion_percentage: 100 } : { status: "not_started", completion_percentage: 0 });

  const showWeek = (week: number) => {
    setSelectedWeekNum(week);
    if (phone) {
      setSelectedStage(null);
      setOpenSkill(null);
    }
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => weekRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
  };

  /** Start a skill: its first task moves to in progress, and its week opens */
  const startSkill = async (skill: JourneySkill) => {
    const first = skill.tasks.find((t) => !isCleared(t.task));
    if (!first) return;
    if (first.task.status === "not_started") {
      const ok = await saveTask(first.task, { status: "in_progress" });
      if (ok) await refreshAfterSave();
    }
    showWeek(first.week);
  };

  /** Mark every remaining task of a skill done, one after another */
  const completeSkill = async (skill: JourneySkill) => {
    setBulkBusy(skill.key);
    try {
      for (const { task } of skill.tasks) {
        if (isCleared(task)) continue;
        const ok = await saveTask(task, { status: "completed", completion_percentage: 100 });
        if (!ok) break;
      }
      await refreshAfterSave();
    } finally {
      setBulkBusy(null);
    }
  };

  const selectStage = (index: number) => {
    setOpenSkill(null);
    setSelectedStage((current) => (current === index ? null : index));
  };

  const selectSkill = (key: string) => {
    const skill = journey.skills.find((s) => s.key === key);
    if (!skill) return;
    setSelectedStage(skill.stage);
    setOpenSkill(key);
  };

  const activeIndex = useMemo(() => {
    const found = weeks.findIndex((week) => week.week_number === selectedWeekNum);
    return found === -1 ? 0 : found;
  }, [selectedWeekNum, weeks]);
  const activeWeek = weeks[activeIndex] ?? null;
  const weekStage = useMemo(() => {
    const first = activeWeek?.tasks?.[0];
    const skill = first ? journey.skills.find((s) => s.tasks.some((t) => t.task.id === first.id)) : null;
    return skill ? journey.stages[skill.stage] ?? null : null;
  }, [activeWeek, journey]);

  const hoursPerWeek = roadmap?.weekly_hours_budget ?? roadmap?.hours_per_week ?? profile?.hours_per_week;
  const adaptiveNotice = showAdaptiveNotice || Boolean((roadmap?.adaptive_rebalance_count ?? 0) > 0);
  const hasJourney = Boolean(roadmap) && journey.stages.length > 0;

  if (loading) {
    return (
      <div className="rm">
        <div className="rm__inner" aria-busy="true">
          <div className="rm-skel rm-skel--head" />
          <div className="rm-skel rm-skel--map" />
          <div className="rm-skel rm-skel--block" />
          <p className="sr-only">Loading your roadmap</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rm">
      <div className="rm__inner">
        <header className="rm-head">
          <div className="rm-head__text">
            <h1 className="rm-title">{roadmap ? `Your road to ${role}` : "Your career journey"}</h1>
            {roadmap && (
              <p className="rm-sub">
                {journey.skills.length} skill{journey.skills.length === 1 ? "" : "s"} in the order you’ll learn them, planned from your analysis
                {hoursPerWeek ? ` at ${hoursPerWeek} h a week` : ""}.
                {roadmap.created_at ? ` Made on ${formatDate(roadmap.created_at)}.` : ""}
              </p>
            )}
          </div>
          <div className="rm-head__actions">
            <Button asChild size="sm" variant="ghost">
              <Link to="/analysis/results">See your analysis</Link>
            </Button>
            {roadmap && (
              <>
                <Button size="sm" variant="ghost" onClick={handleAdaptiveReassess} disabled={reassessing || generating || rebuilding}>
                  {reassessing ? "Updating…" : "Adjust schedule"}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setConfirmRebuild(true)} disabled={generating || rebuilding || !profile?.hours_per_week}>
                  {generating ? "Rebuilding…" : "Rebuild roadmap"}
                </Button>
              </>
            )}
          </div>
        </header>

        {hasJourney && (
          <dl className="rm-glance">
            <div>
              <dt>This week</dt>
              <dd>
                <span className="rm-num">Week {journey.currentWeek ?? journey.weekCount}</span> of {journey.weekCount}
              </dd>
            </div>
            <div>
              <dt>Done</dt>
              <dd>
                <span className="rm-num">{journey.progress}%</span> of planned hours
              </dd>
            </div>
            <div>
              <dt>Still to go</dt>
              <dd>
                <span className="rm-num">{readableHours(journey.remainingMinutes)}</span>
                {hoursPerWeek ? ` at ${hoursPerWeek} h a week` : ""}
              </dd>
            </div>
            <div>
              <dt>Checkpoint</dt>
              <dd>
                <span className="rm-num">
                  {Math.min(journey.currentStage + 1, journey.stages.length)} of {journey.stages.length}
                </span>
              </dd>
            </div>
          </dl>
        )}

        {error && <div className="rm-alert rm-alert--error" role="alert">{error}</div>}

        {roleSync.stage !== "idle" && roleSync.role && (
          <div className={`rm-alert${rebuilding ? " rm-alert--busy" : ""}${roleSync.stage === "failed" ? " rm-alert--error" : ""}`} role="status">
            {rebuilding && <span className="rm-spin" aria-hidden="true" />}
            <span>
              {roleSync.stage === "analysing" && <>You changed your career to <strong>{roleSync.role}</strong>. Re-reading your evidence against it…</>}
              {roleSync.stage === "building" && <>Building your new plan for <strong>{roleSync.role}</strong>…</>}
              {roleSync.stage === "done" && (roleSync.message ?? <><strong>This plan is now for {roleSync.role}.</strong> Your old plan was replaced.</>)}
              {roleSync.stage === "failed" && roleSync.message}
            </span>
            {!rebuilding && (
              <button type="button" className="rm-alert__close" onClick={resetRoleSync} aria-label="Dismiss">
                <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
        )}

        {adaptiveNotice && roadmap && (
          <div className="rm-alert" role="status">
            <strong>Your plan was updated.</strong> Work you’ve already finished is kept. Only what’s ahead changed.
          </div>
        )}

        {!roadmap ? (
          <section className="rm-blank">
            <svg className="rm-blank__road" viewBox="0 0 320 90" aria-hidden="true">
              <path d="M8 70 C 70 70, 70 20, 130 20 S 190 70, 250 70 S 300 30, 312 30" />
              <circle cx="8" cy="70" r="5" />
              <circle cx="312" cy="30" r="5" />
            </svg>
            <h2>Map your road to a role</h2>
            <p>
              {analysis
                ? "INAURA turns your latest skill gaps into a journey: the skills in the order to learn them, with a realistic plan for each week."
                : "Run your analysis first. INAURA then turns your skill gaps into a journey you can follow week by week."}
            </p>
            <div className="rm-blank__actions">
              {analysis ? (
                <Button variant="primary" onClick={handleGenerate} disabled={generating || rebuilding || !profile?.hours_per_week}>
                  {generating ? "Building your plan…" : "Build my roadmap"}
                </Button>
              ) : (
                // Nothing to plan from yet: the analysis comes first, and it lives on Evidence
                <Button asChild variant="primary"><Link to="/analysis">Add evidence and run your analysis</Link></Button>
              )}
              {analysis && !profile?.hours_per_week && (
                <Button asChild variant="secondary"><Link to="/profile">Set your hours per week first</Link></Button>
              )}
            </div>
          </section>
        ) : !hasJourney ? (
          <p className="rm-empty">No weekly tasks yet. Rebuild your plan to fill in its weeks.</p>
        ) : (
          <div className={`rm-plan${rebuilding ? " is-stale" : ""}`} aria-busy={rebuilding || undefined}>
            <section className="rm-journey" aria-label="Your career journey">
              <JourneyMap
                journey={journey}
                horizon={horizon}
                startedAt={roadmap.created_at}
                hoursPerWeek={hoursPerWeek}
                selectedStage={selectedStage}
                onSelectStage={selectStage}
                onSelectSkill={selectSkill}
              />
              <ul className="jr-legend" aria-label="What the marks on the road mean">
                {STATE_ORDER.map((state) => (
                  <li key={state} className={journey.counts[state] ? "" : "is-empty"} title={STATE_META[state].hint}>
                    <StateGlyph state={state} size={14} />
                    <span className="jr-legend__label">{STATE_META[state].label}</span>
                    <span className="jr-legend__count rm-num">{journey.counts[state]}</span>
                    <span className="sr-only">: {STATE_META[state].hint}</span>
                  </li>
                ))}
              </ul>
              {selectedStage === null && <p className="jr-tip">Select a checkpoint or a mark on the road to see why it’s there.</p>}
            </section>

            {selectedStage !== null && journey.stages[selectedStage] && (
              <StageSheet
                journey={journey}
                stage={journey.stages[selectedStage]}
                role={role}
                openSkill={openSkill}
                onOpenSkill={setOpenSkill}
                onSelectStage={(i) => {
                  setOpenSkill(null);
                  setSelectedStage(i);
                }}
                onClose={() => {
                  setSelectedStage(null);
                  setOpenSkill(null);
                }}
                asSheet={phone}
                updating={updating}
                bulkBusy={bulkBusy}
                onToggleTask={toggleTask}
                onStart={startSkill}
                onCompleteSkill={completeSkill}
                onShowWeek={showWeek}
              />
            )}

            <div ref={weekRef} className="rm-weekwrap">
              {activeWeek && (
                <WeekPlan
                  weeks={weeks}
                  week={activeWeek}
                  currentWeek={journey.currentWeek}
                  stage={weekStage}
                  updating={updating}
                  expanded={expanded}
                  onToggleExpanded={(taskId) => setExpanded((current) => ({ ...current, [taskId]: !current[taskId] }))}
                  onUpdateTask={handleUpdateTask}
                  onLaunchAssessment={(skillName, task) => setAssessingTarget({ skillName, task })}
                  onPickWeek={setSelectedWeekNum}
                  onOpenStage={(i) => {
                    setOpenSkill(null);
                    setSelectedStage(i);
                  }}
                />
              )}
            </div>

            <MoveProjection journey={journey} model={model} role={role} hoursPerWeek={hoursPerWeek} />
          </div>
        )}
      </div>

      {assessNote && (
        <div className="rm-toast" role="status">
          <span>{assessNote}</span>
          <button type="button" className="rm-alert__close" onClick={() => setAssessNote(null)} aria-label="Dismiss">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {assessingTarget && (
        <AssessmentModal
          skill={assessingTarget.skillName}
          // The modal stays open on its results either way, so the feedback can be read
          onClose={() => setAssessingTarget(null)}
          onCompleted={async (result) => {
            const target = assessingTarget;
            // A new result changes the analysis this plan was built from
            resultsPageData.fetch(true).catch(() => undefined);
            if (passed(result)) {
              await handleUpdateTask(target.task, { status: "completed", completion_percentage: 100 });
              setAssessNote(`You passed ${target.skillName}. “${target.task.title}” is marked done.`);
            } else {
              setAssessNote(
                `${target.skillName}: ${Math.round(result.score * 100)}%. Reaching ${Math.round(PASS_SCORE * 100)}% completes this task. Review the feedback and try again when you’re ready.`
              );
            }
          }}
        />
      )}

      {confirmRebuild && (
        <div className="rm-confirm" onClick={() => setConfirmRebuild(false)}>
          <div
            className="rm-confirm__panel"
            ref={rebuildRef}
            tabIndex={-1}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="rm-confirm-title"
            aria-describedby="rm-confirm-text"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="rm-confirm-title">Rebuild your roadmap?</h2>
            <p id="rm-confirm-text">
              INAURA will make a new plan from your latest analysis. This plan and the {journey.progress}% of it you’ve done will be replaced.
              To keep your progress and only fit the remaining weeks to your time, use “Adjust schedule” instead.
            </p>
            <div className="rm-confirm__actions">
              <Button variant="secondary" onClick={() => setConfirmRebuild(false)} data-autofocus>
                Keep this plan
              </Button>
              <Button variant="primary" onClick={handleGenerate}>
                Rebuild it
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
