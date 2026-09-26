import { useEffect, useState } from "react";
import "./Person2.css";
import {
  createAlignment,
  createPlacement,
  getDashboard,
  listAlignments,
  listPlacements,
  type Alignment,
  type Dashboard,
  type Placement,
} from "../services/outcomes";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pct = (v: number) => `${Math.round(v * 100)}%`;

export default function Outcomes() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [alignments, setAlignments] = useState<Alignment[]>([]);
  const [roleTitle, setRoleTitle] = useState("");
  const [employerId, setEmployerId] = useState("");
  const [courseName, setCourseName] = useState("");
  const [requirementId, setRequirementId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    try {
      const [d, p, a] = await Promise.all([getDashboard(), listPlacements(), listAlignments()]);
      setDashboard(d);
      setPlacements(p);
      setAlignments(a);
    } catch (e) {
      setError(messageOf(e));
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const addPlacement = async () => {
    if (!employerId.trim() || !roleTitle.trim()) {
      setError("Employer ID and role title are required for a placement");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createPlacement({
        employer_id: employerId.trim(),
        role_title: roleTitle.trim(),
        status: "joined",
      });
      setEmployerId("");
      setRoleTitle("");
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const addAlignment = async () => {
    if (!requirementId.trim() || !courseName.trim()) {
      setError("Requirement ID and course name are required for an alignment");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createAlignment({
        hiring_requirement_id: requirementId.trim(),
        course_name: courseName.trim(),
      });
      setRequirementId("");
      setCourseName("");
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="p2">
      <header className="p2__head">
        <h1>Outcomes</h1>
        <p>
          Descriptive outcome signals only — counts and rates, never predictions. Readiness is a
          development indicator, not a hiring probability.
        </p>
      </header>
      {error && <p className="p2__error">{error}</p>}

      <section>
        <h2>Funnel</h2>
        {!dashboard ? (
          <p>Loading dashboard…</p>
        ) : (
          <>
            <p className="p2__hint">
              Based on {dashboard.denominators.applied_n} applied application(s)
              {dashboard.unlinked_placements_n > 0 &&
                ` · ${dashboard.unlinked_placements_n} placement(s) recorded without a linked application are excluded from joining rates`}
              .
            </p>
            <ul className="p2__list p2__funnel">
              {Object.entries(dashboard.funnel).map(([status, n]) => (
                <li key={status}>
                  {status}: <strong>{n}</strong>
                </li>
              ))}
            </ul>
            <ul className="p2__list">
              <li>
                Application → interview: <strong>{pct(dashboard.rates.interview_rate)}</strong>
              </li>
              <li>
                Application → offer: <strong>{pct(dashboard.rates.offer_rate)}</strong>
              </li>
              <li>
                Application → selection: <strong>{pct(dashboard.rates.selection_rate)}</strong>
              </li>
              <li>
                Selection → joining:{" "}
                <strong>{pct(dashboard.rates.joining_rate_selection_base)}</strong> (of{" "}
                {dashboard.denominators.selected_n} selected)
              </li>
              <li>
                Application → joining:{" "}
                <strong>{pct(dashboard.rates.joining_rate_application_base)}</strong>
              </li>
            </ul>
            {dashboard.top_required_skills.length > 0 && (
              <>
                <h3>Most requested skills</h3>
                <ul className="p2__list">
                  {dashboard.top_required_skills.map((s) => (
                    <li key={s.skill_id}>
                      <code>{s.skill_id.slice(0, 8)}…</code> · {s.count} requirement(s)
                    </li>
                  ))}
                </ul>
              </>
            )}
            {dashboard.top_observed_gaps.length > 0 && (
              <>
                <h3>Largest employer-observed gaps</h3>
                <ul className="p2__list">
                  {dashboard.top_observed_gaps.map((g) => (
                    <li key={g.skill_id}>
                      <code>{g.skill_id.slice(0, 8)}…</code> · avg gap{" "}
                      {Math.round(g.avg_gap * 100)}pp across {g.feedback_count} observation(s)
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </section>

      <div className="p2__cols">
        <section>
          <h2>Placements</h2>
          <ul className="p2__list">
            {placements.map((p) => (
              <li key={p.id} className="p2__card">
                <strong>{p.role_title}</strong> · {p.status} · {p.verification_status}
              </li>
            ))}
            {placements.length === 0 && <li>No placements recorded.</li>}
          </ul>
          <div className="p2__form">
            <input
              aria-label="Employer ID"
              placeholder="Employer ID"
              value={employerId}
              onChange={(e) => setEmployerId(e.target.value)}
            />
            <input
              aria-label="Role title"
              placeholder="Role title"
              value={roleTitle}
              onChange={(e) => setRoleTitle(e.target.value)}
            />
            <button type="button" onClick={addPlacement} disabled={saving}>
              {saving ? "Saving…" : "Record placement"}
            </button>
          </div>
        </section>
        <section>
          <h2>Course alignments</h2>
          <ul className="p2__list">
            {alignments.map((a) => (
              <li key={a.id} className="p2__card">
                <strong>{a.course_name}</strong>
                {a.qualification_name && <span> · {a.qualification_name}</span>}
                {a.coverage != null && <span> · covers {pct(a.coverage)}</span>}
              </li>
            ))}
            {alignments.length === 0 && <li>No alignments yet.</li>}
          </ul>
          <div className="p2__form">
            <input
              aria-label="Requirement ID"
              placeholder="Requirement ID"
              value={requirementId}
              onChange={(e) => setRequirementId(e.target.value)}
            />
            <input
              aria-label="Course name"
              placeholder="Course name"
              value={courseName}
              onChange={(e) => setCourseName(e.target.value)}
            />
            <button type="button" onClick={addAlignment} disabled={saving}>
              {saving ? "Saving…" : "Add alignment"}
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
