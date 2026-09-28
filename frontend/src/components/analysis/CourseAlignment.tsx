import { useState } from "react";
import { getCourseAlignment, type CourseAlignmentResponse } from "../../services/industry";

const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const share = (v?: number | null) => v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

// Small additive course-alignment view for the Industry Intelligence page.
// Evidence-first rows (demand → curriculum → cohort supply → status); takes a
// course ID (+ optional cohort ID) and queries the deterministic P0 #4
// projection. Insufficient/suppressed data is labelled, never hidden.
export default function CourseAlignment({ role }: { role: string }) {
  const [courseId, setCourseId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [applied, setApplied] = useState<{ course_id: string; cohort_id?: string } | null>(null);
  const [data, setData] = useState<CourseAlignmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const cid = courseId.trim();
    if (!cid) return;
    const next = { course_id: cid, cohort_id: cohortId.trim() || undefined };
    setApplied(next);
    setLoading(true);
    setError(null);
    getCourseAlignment({ ...next, role })
      .then((r) => { setData(r); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "Course alignment unavailable."); setLoading(false); });
  };

  return <section aria-label="Course alignment">
    <div className="an-overview__bar"><span><strong>Course alignment</strong><span className="an-faint"> · deterministic demand × curriculum × cohort supply</span></span><form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><label className="an-faint" htmlFor="align-course">Course ID</label><input id="align-course" value={courseId} onChange={(e) => setCourseId(e.target.value)} placeholder="course UUID" style={{ maxWidth: 260 }} /><label className="an-faint" htmlFor="align-cohort">Cohort ID</label><input id="align-cohort" value={cohortId} onChange={(e) => setCohortId(e.target.value)} placeholder="optional" style={{ maxWidth: 200 }} /><button type="submit" className="an-link an-link--btn">Evaluate</button></form></div>
    {!applied && <p className="an-note">Enter a course ID to evaluate its alignment against {role} demand. No scores are computed without evidence.</p>}
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
