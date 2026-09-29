import { useEffect, useState } from "react";
import {
  getCourseAlignment,
  getCourseCoverage,
  listCourseCohorts,
  listCourses,
  listInstitutions,
  type Cohort,
  type Course,
  type CourseAlignmentResponse,
  type CourseCoverage,
  type Institution,
} from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const share = (v?: number | null) => v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

// Course-alignment view.
// Flow: pick institution → pick course (or paste a course ID directly) →
// review the course's full details (record + curriculum coverage) → optional
// cohort → Evaluate. Evidence-first rows (demand → curriculum → cohort
// supply → status); insufficient/suppressed data is labelled, never hidden.
export default function CourseAlignment({ role }: { role: string }) {
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [instLoading, setInstLoading] = useState(true);
  const [instError, setInstError] = useState<string | null>(null);
  const [instId, setInstId] = useState("");

  const [courses, setCourses] = useState<Course[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [courseId, setCourseId] = useState("");
  const [manualId, setManualId] = useState("");

  const [coverage, setCoverage] = useState<CourseCoverage | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);

  const [cohorts, setCohorts] = useState<Cohort[]>([]);
  const [cohortId, setCohortId] = useState("");

  const [applied, setApplied] = useState<{ course_id: string; cohort_id?: string } | null>(null);
  const [data, setData] = useState<CourseAlignmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1: institutions drive everything else
  useEffect(() => {
    let cancelled = false;
    setInstLoading(true);
    setInstError(null);
    listInstitutions()
      .then((rows) => { if (!cancelled) { setInstitutions(rows); setInstLoading(false); } })
      .catch((e: unknown) => {
        if (!cancelled) {
          setInstError(e instanceof Error ? e.message : "Institutions could not be loaded.");
          setInstLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, []);

  // Step 2: courses for the chosen institution
  useEffect(() => {
    setCourses([]);
    setCourseId("");
    if (!instId) return;
    let cancelled = false;
    setCoursesLoading(true);
    listCourses(instId)
      .then((rows) => { if (!cancelled) { setCourses(rows); setCoursesLoading(false); } })
      .catch(() => { if (!cancelled) setCoursesLoading(false); });
    return () => { cancelled = true; };
  }, [instId]);

  // Step 3: full course details (record + curriculum coverage) and cohorts.
  // Shown BEFORE evaluation — nothing is scored sight-unseen.
  useEffect(() => {
    setCoverage(null);
    setDetailsError(null);
    setCohorts([]);
    setCohortId("");
    setApplied(null);
    setData(null);
    setError(null);
    if (!courseId) return;
    let cancelled = false;
    setDetailsLoading(true);
    Promise.all([
      getCourseCoverage(courseId).catch(() => null),
      listCourseCohorts(courseId).catch(() => [] as Cohort[]),
    ]).then(([cov, chs]) => {
      if (cancelled) return;
      setCoverage(cov);
      if (!cov) setDetailsError("Course curriculum details are unavailable for this course.");
      setCohorts(chs);
      setDetailsLoading(false);
    });
    return () => { cancelled = true; };
  }, [courseId, role]);

  // Details prefer the picker record, falling back to the coverage payload
  // so a pasted ID still shows full course details before evaluation.
  const course = courses.find((c) => c.id === courseId) ?? coverage?.course ?? null;
  const institution =
    institutions.find((i) => i.id === (course?.institution_id ?? instId)) ?? null;

  const loadManualId = (e: React.FormEvent) => {
    e.preventDefault();
    const id = manualId.trim();
    if (!id) return;
    setCourseId(id);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!courseId) return;
    const next = { course_id: courseId, cohort_id: cohortId || undefined };
    setApplied(next);
    setLoading(true);
    setError(null);
    getCourseAlignment({ ...next, role })
      .then((r) => { setData(r); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Course alignment unavailable."); setLoading(false); });
  };

  const taughtCount = coverage
    ? coverage.modules.reduce((n, m) => n + m.skills.length, 0) + coverage.course_level_skills.length
    : 0;

  return <section aria-label="Course alignment">
    <div className="an-overview__bar">
      <span><strong>Course alignment</strong><span className="an-faint"> · deterministic demand × curriculum × cohort supply</span></span>
    </div>

    {instLoading && <div className="an-skel an-skel--block" aria-label="Loading institutions" />}
    {instError && <p className="an-empty">{instError}</p>}
    {!instLoading && !instError && institutions.length === 0 && (
      <p className="an-note">No institutions are registered yet, so there is nothing to align. Register an institution and its courses first (or seed the deterministic demo supply), then return here to evaluate.</p>
    )}
    {!instLoading && !instError && institutions.length > 0 && (
      <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <label className="an-faint" htmlFor="align-inst">Institution</label>
        <select id="align-inst" value={instId} onChange={(e) => setInstId(e.target.value)} style={{ maxWidth: 280 }}>
          <option value="">Choose institution…</option>
          {institutions.map((i) => (
            <option key={i.id} value={i.id}>{i.name}{i.district ? ` · ${i.district}` : ""}</option>
          ))}
        </select>
        <label className="an-faint" htmlFor="align-course">Course</label>
        <select id="align-course" value={courseId} onChange={(e) => { setCourseId(e.target.value); setManualId(""); }} disabled={!instId || coursesLoading} style={{ maxWidth: 280 }}>
          <option value="">{!instId ? "Pick an institution first" : coursesLoading ? "Loading courses…" : "Choose course…"}</option>
          {courses.map((c) => (
            <option key={c.id} value={c.id}>{c.name}{c.code ? ` (${c.code})` : ""}</option>
          ))}
        </select>
        <label className="an-faint" htmlFor="align-cohort">Cohort</label>
        <select id="align-cohort" value={cohortId} onChange={(e) => setCohortId(e.target.value)} disabled={!courseId} style={{ maxWidth: 240 }}>
          <option value="">Combined supply (all cohorts)</option>
          {cohorts.map((c) => (
            <option key={c.id} value={c.id}>{c.name}{c.academic_year ? ` · ${c.academic_year}` : ""}</option>
          ))}
        </select>
        <button type="submit" className="an-link an-link--btn" disabled={!courseId || loading}>
          {loading ? "Evaluating…" : "Evaluate"}
        </button>
      </form>
    )}

    {instId && !coursesLoading && courses.length === 0 && (
      <p className="an-note">{institution?.name ?? "This institution"} has no courses registered yet.</p>
    )}

    {!instLoading && !instError && (
      <form onSubmit={loadManualId} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <label className="an-faint" htmlFor="align-course-id">Course ID</label>
        <input id="align-course-id" value={manualId} onChange={(e) => setManualId(e.target.value)} placeholder="paste a course UUID directly" style={{ maxWidth: 320 }} />
        <button type="submit" className="an-link an-link--btn" disabled={!manualId.trim()}>
          Load
        </button>
      </form>
    )}

    {detailsLoading && <div className="an-skel an-skel--block" aria-label="Loading course details" />}
    {detailsError && !detailsLoading && <p className="an-empty">{detailsError}</p>}
    {course && !detailsLoading && (
      <div style={{ background: "var(--paper-2, #f8fafc)", padding: "0.85rem 1rem", borderRadius: "8px", marginBottom: "1rem", border: "1px solid var(--line)" }}>
        <div style={{ fontSize: "0.8rem", fontWeight: 700, textTransform: "uppercase", color: "var(--muted)", marginBottom: "0.4rem" }}>
          Selected course — review before evaluating
        </div>
        <div style={{ fontSize: "1rem", fontWeight: 700 }}>{course.name}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.5rem", fontSize: "0.85rem", marginTop: "0.4rem" }}>
          <div>Institution: <strong>{institution?.name || "—"}</strong></div>
          <div>Code: <strong>{course.code || "—"}</strong></div>
          <div>Level: <strong>{course.level || "—"}</strong></div>
          <div>Duration: <strong>{course.duration_text || "—"}</strong></div>
          <div>Delivery: <strong>{course.delivery_mode ? titleCase(course.delivery_mode) : "—"}</strong></div>
          <div>Status: <strong>{titleCase(course.status)}</strong></div>
        </div>
        {course.description && (
          <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0.5rem 0 0" }}>{course.description}</p>
        )}
        {coverage && (
          <div style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
            Curriculum: <strong>{coverage.modules.length} module{coverage.modules.length === 1 ? "" : "s"}</strong> ·{" "}
            <strong>{taughtCount} taught skill{taughtCount === 1 ? "" : "s"}</strong>
            {coverage.modules.length > 0 && (
              <span style={{ color: "var(--muted)" }}> ({coverage.modules.map((m) => m.module_name || "Untitled module").join(" · ")})</span>
            )}
          </div>
        )}
        {courseId && cohorts.length === 0 && !detailsLoading && (
          <p className="an-note" style={{ margin: "0.5rem 0 0" }}>No cohorts for this course yet — evaluation will use course-combined supply (cohort detail will read as insufficient evidence).</p>
        )}
      </div>
    )}

    {!applied && course && <p className="an-note">Review the course details above, then Evaluate to align it against {role} demand. No scores are computed without evidence.</p>}
    {loading && <div className="an-skel an-skel--block" aria-label="Loading course alignment" />}
    {error && <p className="an-empty">{error}</p>}
    {!loading && !error && data && <>
      {data.role_mapping_status === "unmapped" && <p className="an-note"><strong>Role not mapped.</strong> {data.note}</p>}
      <p className="an-note"><strong>{data.course?.name ?? "Course"}</strong><span className="an-faint"> · market skills: {data.summary?.total_market_skills ?? 0} · covered: {data.summary?.covered_market_skills ?? 0} · missing: {data.summary?.missing_market_skills ?? 0} · weak supply: {data.summary?.weak_attainment_skills ?? 0}{data.cohort_context?.suppressed ? " · cohort detail suppressed (small sample)" : ""}</span></p>
      {data.skills.length === 0 && <p className="an-note">No alignment rows — {data.note || "insufficient evidence for this role and course."}</p>}
      <ul className="an-skills">{data.skills.slice(0, 12).map((s) => <li key={s.skill} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{s.display_name || s.skill}</span><span className="an-skill__status">{titleCase(s.alignment.overall_status)}</span></div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts">
        <div><dt>Industry demand</dt><dd>{s.industry ? <>{titleCase(s.alignment.demand_status)} <span className="an-faint">(share {share(s.industry.skill_share)} · {s.industry.skill_posting_count ?? "—"} of {s.industry.posting_count ?? "—"} postings)</span></> : "No market evidence"}</dd></div>
        <div><dt>Course</dt><dd>{s.curriculum ? <>{titleCase(s.alignment.curriculum_status)} <span className="an-faint">({titleCase(s.curriculum.coverage) ?? "coverage unstated"}{s.curriculum.modules.length ? ` · ${s.curriculum.modules.join(", ")}` : ""})</span></> : "Not covered"}</dd></div>
        <div><dt>Cohort verified</dt><dd>{s.cohort ? <>{share(s.cohort.verified_coverage)} <span className="an-faint">({s.cohort.verified_member_count ?? "—"} of {s.cohort.evidenced_member_count ?? "—"} evidenced)</span></> : "Insufficient evidence"}</dd></div>
        {s.alignment.priority_reasons.length > 0 && <div><dt>Reasons</dt><dd>{s.alignment.priority_reasons.join(" · ")}</dd></div>}
      </dl></div></li>)}</ul>
      {data.skills.length > 12 && <p className="an-note">Showing 12 of {data.skills.length} skills — full detail is available from the API.</p>}
    </>}
  </section>;
}
