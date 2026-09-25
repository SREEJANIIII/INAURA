import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { setTargetRole, type RoleSummary } from "../services/industry";
import { updateRoadmapTask, type RoadmapTask } from "../services/roadmap";
import {
  analysisStateData,
  capabilityMapData,
  evidencePageData,
  profileData,
  resultsPageData,
  roadmapPageData,
  roleCatalogData,
  subscribePageData,
} from "../lib/pageData";
import {
  buildActions,
  buildActivity,
  buildCoverage,
  buildInsights,
  buildSignal,
  currentWeek,
  greeting,
} from "../components/home/homeModel";
import RoleSyncNotice from "../components/career-track/RoleSyncNotice";
import { getRoleSync, rebuildForRole, refreshAnalysis, subscribeRoleSync } from "../lib/roleSync";
import { freshness, type StaleReason } from "../lib/analysisFreshness";
import { buildTrack, currentSkill, findRole, roleId } from "../components/career-track/careerTrackModel";
import { navigateWithTransition, useCountUp, useInViewOnce } from "../components/career-track/motion";
import { ProgressBar } from "../components/career-track/Progress";
import CareerPath from "../components/career-track/CareerPath";
import HomeAside from "../components/career-track/HomeAside";
import CareerSwitcher from "../components/career-track/CareerSwitcher";
import "../components/career-track/CareerTrack.css";
import Button from "@/components/ui/app-button";
import { friendlyError, statusOf } from "../lib/errors";
import { dueCount } from "../lib/revision/store";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "");
const isNotFound = (msg: string) => msg.includes("404") || msg.toLowerCase().includes("not found") || msg.toLowerCase().includes("no analysis");

const errorText = (e: unknown) => {
  const msg = messageOf(e);
  if (msg.includes("401")) return "Your session has expired. Log in again to see your career track.";
  if (msg.toLowerCase().includes("profile")) return "Finish setting up your profile first. Career Track reads your skills from it.";
  if (msg.includes("No industry requirements")) return "INAURA doesn’t have industry benchmarks for this role yet.";
  return "Your career track couldn’t be loaded. Check your connection and try again.";
};

export default function CareerTrack() {
  const { careerId } = useParams();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();

  // Every page shares these remembered copies, so home appears instantly after the first load
  const profile = useSyncExternalStore(subscribePageData, profileData.peek);
  const catalog = useSyncExternalStore(subscribePageData, roleCatalogData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const results = useSyncExternalStore(subscribePageData, resultsPageData.peek);
  const roadmap = useSyncExternalStore(subscribePageData, roadmapPageData.peek);
  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);

  const [fatal, setFatal] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<{ role: string; message: string } | null>(null);
  const [switching, setSwitching] = useState(false);
  const [busyRole, setBusyRole] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [noAnalysis, setNoAnalysis] = useState(false);
  // Revision cards waiting, so "Next up" can include a few minutes of revision
  const [revisionDue] = useState(() => (user ? dueCount(user.id, Date.now()) : 0));

  const targetTitle = (analysisState ?? evidence?.analysisState)?.target_role ?? null;
  const stateKnown = !!analysisState || !!evidence;
  const role = catalog ? findRole(catalog, careerId) : undefined;
  const mapEntry = role ? capabilityMapData(role.title) : null;
  const map = useSyncExternalStore(subscribePageData, () => mapEntry?.peek());

  // Opening a career (or switching to another) starts at the top of its path
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [careerId]);

  const load = useCallback(
    (force: boolean) => {
      // The profile decides whether this account is set up at all
      profileData.fetch(force).catch((e) => {
        const msg = messageOf(e);
        const lower = msg.toLowerCase();
        if (statusOf(e) === 404 || isNotFound(msg)) {
          navigate("/profile/setup", { replace: true });
        } else if (msg.includes("401") || lower.includes("not authenticated") || lower.includes("invalid token")) {
          setFatal("Your session has expired. Log in again to continue.");
        } else if (!profileData.peek() && (msg.includes("503") || lower.includes("supabase not configured") || lower.includes("permission denied"))) {
          setFatal("The profiles table isn’t accessible. Run the latest SQL in Supabase (backend/supabase/001_create_profiles.sql).");
        }
      });
      roleCatalogData.fetch(force).catch((e) => setCatalogError(errorText(e)));
      // Which career to open is all this needs, and it's one small call — asking for it
      // directly means the redirect below doesn't wait on the whole evidence bundle
      analysisStateData.fetch(force).catch(() => undefined);
      evidencePageData.fetch(force).catch(() => undefined);
      roadmapPageData.fetch(force).catch(() => undefined);
      resultsPageData
        .fetch(force)
        .then(() => setNoAnalysis(false))
        .catch((e) => setNoAnalysis(isNotFound(messageOf(e))));
    },
    [navigate]
  );

  useEffect(() => {
    load(false);
  }, [load]);

  useEffect(() => {
    if (!role || !mapEntry) return;
    mapEntry.fetch().catch((e) => setMapError({ role: role.title, message: errorText(e) }));
  }, [role, mapEntry]);

  const analysis = noAnalysis ? null : results?.analysis ?? null;
  const track = useMemo(() => (role && map ? buildTrack({ role, map, analysis }) : null), [role, map, analysis]);
  const current = useMemo(() => (track ? currentSkill(track.phases) : null), [track]);

  /* Supporting information, from the same data the dashboard used */
  const coverage = useMemo(
    () => buildCoverage(evidence?.evidence ?? [], evidence?.projects ?? [], evidence?.certs ?? []),
    [evidence]
  );
  const signal = useMemo(() => buildSignal(analysis ? results?.gaps ?? [] : []), [analysis, results]);
  const week = useMemo(() => currentWeek(roadmap?.roadmap ?? null, roadmap?.weeks ?? []), [roadmap]);
  const actions = useMemo(
    () =>
      buildActions({
        analysis,
        roadmap: roadmap?.roadmap ?? null,
        weeks: roadmap?.weeks ?? [],
        coverage: coverage.items,
        assessable: analysis ? results?.assessable ?? [] : [],
        revisionDue,
        limit: 4,
      }),
    [analysis, roadmap, coverage.items, results, revisionDue]
  );
  const insights = useMemo(() => buildInsights(signal, analysis), [signal, analysis]);
  const activity = useMemo(
    () =>
      buildActivity({
        analysis,
        evidence: evidence?.evidence ?? [],
        projects: evidence?.projects ?? [],
        certs: evidence?.certs ?? [],
        roadmap: roadmap?.roadmap ?? null,
        weeks: roadmap?.weeks ?? [],
        limit: 4,
      }),
    [analysis, evidence, roadmap]
  );

  const toggleTask = async (task: RoadmapTask, done: boolean) => {
    // The same update the Roadmap page makes when a task is ticked
    await updateRoadmapTask(task.id, {
      status: done ? "completed" : "in_progress",
      completion_percentage: done ? 100 : Math.min(task.completion_percentage, 99),
    });
    roadmapPageData.fetch(true).catch(() => undefined);
  };

  const selectCareer = async (next: RoleSummary) => {
    setBusyRole(roleId(next));
    setSwitchError(null);
    try {
      // The career track is INAURA's target role, so the rest of the app follows the choice
      await setTargetRole(next.title);
      evidencePageData.fetch(true).catch(() => undefined);
      // Your analysis and plan are tied to the old role, so rebuild both in the background.
      // Nothing to catch up on if you've never run an analysis.
      if (results?.analysis || evidence?.analysisState?.status === "completed") {
        rebuildForRole(next.title);
      }
      setSwitching(false);
      navigateWithTransition(navigate, `/career-track/${roleId(next)}`);
    } catch (e) {
      setSwitchError(friendlyError(e, "Your target role couldn’t be changed. Try again in a moment."));
    } finally {

      setBusyRole(null);
    }
  };

  const handleLogout = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  /* ---------- Account-level problems ---------- */

  if (fatal) {
    return (
      <div className="ct">
        <div className="ct__inner">
          <section className="ct-state" role="alert">
            <h1 className="ct-state__title">Can’t open your career track</h1>
            <p>{fatal}</p>
            <div className="ct-actions">
              <Button variant="primary" onClick={() => window.location.reload()}>Try again</Button>
              <Button variant="secondary" onClick={handleLogout}>Log out</Button>
            </div>
          </section>
        </div>
      </div>
    );
  }

  /* ---------- No career chosen yet ---------- */

  if (!careerId) {
    if (catalog && stateKnown) {
      const target = targetTitle ? catalog.find((r) => r.title.toLowerCase() === targetTitle.toLowerCase()) : undefined;
      if (target) return <Navigate to={`/career-track/${roleId(target)}`} replace />;
    }
    return (
      <div className="ct">
        <div className="ct__inner">
          <header className="ct-head ct-head--intro">
            <p className="ct-hello">{greeting()}{profile?.full_name ? `, ${profile.full_name.split(" ")[0]}` : ""}</p>
            <h1 className="ct-title">Choose the career you’re working towards</h1>
            <p className="ct-lead">INAURA maps the skills it requires, shows where you stand on each, and orders them into a path you can follow.</p>
          </header>
          {catalogError ? (
            <p className="ct-error" role="alert">{catalogError}</p>
          ) : !catalog || !stateKnown ? (
            <div className="ct-skel ct-skel--grid" aria-busy="true" />
          ) : (
            <div className="ct-choose">
              {catalog.map((r) => (
                <button key={roleId(r)} type="button" className="ct-role" onClick={() => selectCareer(r)} disabled={!!busyRole}>
                  <span className="ct-role__title">{r.title}</span>
                  <span className="ct-role__desc">{r.description}</span>
                  {busyRole === roleId(r) && <span className="ct-role__busy">Setting up…</span>}
                </button>
              ))}
            </div>
          )}
          {switchError && <p className="ct-error" role="alert">{switchError}</p>}
        </div>
      </div>
    );
  }

  /* ---------- Unknown career in the URL ---------- */

  if (catalog && !role) {
    return (
      <div className="ct">
        <div className="ct__inner">
          <section className="ct-state">
            <h1 className="ct-state__title">That career track doesn’t exist</h1>
            <p>INAURA has industry benchmarks for {catalog.length} roles. Pick one to see its path.</p>
            <Button variant="primary" onClick={() => setSwitching(true)}>Choose a career</Button>
          </section>
        </div>
        {switching && (
          <CareerSwitcher roles={catalog} currentId={null} targetTitle={targetTitle} busyId={busyRole} onSelect={selectCareer} onClose={() => setSwitching(false)} />
        )}
      </div>
    );
  }

  const failed = mapError && role && mapError.role === role.title && !map ? mapError.message : null;
  const firstName = (profile?.full_name || user?.email?.split("@")[0] || "there").trim().split(/\s+/)[0];

  return (
    <div className="ct">
      <div className="ct__inner">
        {!track ? (
          failed || catalogError ? (
            <section className="ct-state">
              <h1 className="ct-state__title">{role?.title ?? "Career Track"}</h1>
              <p>{failed || catalogError}</p>
              <Button variant="primary"
                onClick={() => {
                  setMapError(null);
                  setCatalogError(null);
                  load(true);
                  if (role) capabilityMapData(role.title).fetch(true).catch((e) => setMapError({ role: role.title, message: errorText(e) }));
                }}
              >
                Try again
              </Button>
            </section>
          ) : (
            <HomeSkeleton title={role?.title} name={firstName} />
          )
        ) : (
          <>
            <HomeHeader
              name={firstName}
              track={track}
              current={current?.name ?? null}
              analysedOn={analysis ? new Date(analysis.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : null}
              outdated={
                track.readiness.source !== "analysis"
                  ? null
                  : freshness({ analysis, targetRole: targetTitle }).reason
              }
              onRefresh={() => refreshAnalysis(track.title)}
              isTarget={!!targetTitle && targetTitle.toLowerCase() === track.title.toLowerCase()}
              onChange={() => setSwitching(true)}
              onMakeTarget={() => role && selectCareer(role)}
              busy={!!busyRole}
            />
            {switchError && <p className="ct-error" role="alert">{switchError}</p>}
            <RoleSyncNotice />

            <div className="ct-home">
              <section className="ct-home__path" aria-labelledby="ct-path-title">
                <div className="ct-sec__head">
                  <h2 id="ct-path-title">Your path</h2>
                  <p>Every skill {track.title} roles ask for, in the order that builds on itself. Open one to see its topics and next steps.</p>
                </div>
                <CareerPath phases={track.phases} careerId={track.id} current={current} />
              </section>

              <HomeAside
                weekNumber={week?.week_number}
                actions={actions}
                priority={track.priority}
                careerId={track.id}
                coverage={coverage}
                insights={insights}
                activity={activity}
                onToggleTask={toggleTask}
              />
            </div>
          </>
        )}
      </div>

      {switching && catalog && (
        <CareerSwitcher
          roles={catalog}
          currentId={role ? roleId(role) : null}
          targetTitle={targetTitle}
          busyId={busyRole}
          onSelect={selectCareer}
          onClose={() => setSwitching(false)}
        />
      )}
    </div>
  );
}

function HomeHeader({
  name,
  track,
  current,
  analysedOn,
  outdated,
  onRefresh,
  isTarget,
  onChange,
  onMakeTarget,
  busy,
}: {
  name: string;
  track: NonNullable<ReturnType<typeof buildTrack>>;
  current: string | null;
  analysedOn: string | null;
  /** Why the analysis's readiness no longer holds, if it doesn't */
  outdated: StaleReason | null;
  onRefresh: () => void;
  isTarget: boolean;
  onChange: () => void;
  onMakeTarget: () => void;
  busy: boolean;
}) {
  const [ref, inView] = useInViewOnce<HTMLDivElement>();
  const readiness = useCountUp(track.readiness.value, inView);
  const { counts, skills } = track;
  const sync = useSyncExternalStore(subscribeRoleSync, getRoleSync);
  const rerunning = sync.stage === "analysing" || sync.stage === "building";

  return (
    <header className="ct-head">
      <div className="ct-head__intro">
        <p className="ct-hello">{greeting()}, {name}</p>
        <h1 className="ct-title" style={{ viewTransitionName: "ct-career-title" }}>
          Your path to {track.title}
        </h1>
        <p className="ct-lead">
          <span className="ct-num">{counts.completed}</span> of <span className="ct-num">{skills.length}</span> skills are at the level this role asks for.
          {current ? ` ${current} is where you are now.` : " Every skill on your path is ready."}
        </p>
        <div className="ct-head__actions">
          <Button variant="secondary" onClick={onChange}>Change career</Button>
          {!isTarget && (
            <Button variant="primary" onClick={onMakeTarget} disabled={busy}>
              {busy ? "Saving…" : "Make this my target role"}
            </Button>
          )}
        </div>
      </div>

      <div ref={ref} className={`ct-ready${inView ? " is-in" : ""}`}>
        <div className="ct-ready__top">
          <span className="ct-ready__label">Career readiness</span>
          <span className={outdated ? "ct-ready__source ct-ready__source--outdated" : "ct-ready__source"}>
            {outdated ? "Out of date" : track.readiness.source === "analysis" ? "From your analysis" : "Estimated"}
          </span>
        </div>
        <p className="ct-ready__num ct-num">
          {readiness}
          <span>%</span>
        </p>
        <ProgressBar value={track.readiness.value} size="lg" label="Career readiness" />
        <dl className="ct-counts">
          <div className="ct-counts__item ct-counts__item--completed">
            <dt>Ready</dt>
            <dd className="ct-num">{counts.completed}</dd>
          </div>
          <div className="ct-counts__item ct-counts__item--in-progress">
            <dt>In progress</dt>
            <dd className="ct-num">{counts["in-progress"]}</dd>
          </div>
          <div className="ct-counts__item ct-counts__item--not-started">
            <dt>To start</dt>
            <dd className="ct-num">{counts["not-started"] + counts.locked}</dd>
          </div>
        </dl>
        {analysedOn && <p className="ct-ready__foot ct-faint">Analysed {analysedOn}</p>}
        {outdated && (
          <div className="ct-ready__outdated">
            <p>
              {outdated === "evidence"
                ? "Your evidence has changed since this analysis."
                : outdated === "role"
                  ? "This analysis was run against a different role."
                  : "INAURA’s readiness scoring has been improved since this analysis."}{" "}
              Re-run it to update this score.
            </p>
            <Button variant="secondary" size="sm" onClick={onRefresh} disabled={rerunning}>
              {rerunning ? "Re-running…" : "Re-run analysis"}
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}

function HomeSkeleton({ title, name }: { title?: string; name: string }) {
  return (
    <div aria-busy="true">
      <header className="ct-head">
        <div className="ct-head__intro">
          <p className="ct-hello">{greeting()}, {name}</p>
          {title ? <h1 className="ct-title">Your path to {title}</h1> : <div className="ct-skel ct-skel--title" />}
          <p className="ct-muted">Reading your evidence against this role…</p>
        </div>
        <div className="ct-skel ct-skel--ready" />
      </header>
      <div className="ct-home">
        <div className="ct-skel ct-skel--path" />
        <div className="ct-skel ct-skel--aside" />
      </div>
    </div>
  );
}
