import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, type AnalysisResult } from "../services/analysis";
import { getProfile, type Profile } from "../services/profile";
import {
  generateRoadmap,
  getLatestRoadmap,
  getRoadmapItems,
  getRoadmapMilestones,
  updateRoadmapItem,
  type Roadmap,
  type RoadmapItem,
  type RoadmapMilestone,
} from "../services/roadmap";
import Button from "../components/ui/Button";
import "./Roadmap.css";

export default function Roadmap() {
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [items, setItems] = useState<RoadmapItem[]>([]);
  const [milestones, setMilestones] = useState<RoadmapMilestone[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [updating, setUpdating] = useState<string | null>(null);

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [prof, ana] = await Promise.all([
        getProfile().catch(() => null),
        getLatestAnalysis().catch(() => null),
      ]);
      setProfile(prof);
      setAnalysis(ana);
      // Try to load roadmap, items, milestones
      try {
        const [rm, its, ms] = await Promise.all([
          getLatestRoadmap(),
          getRoadmapItems().catch(() => [] as RoadmapItem[]),
          getRoadmapMilestones().catch(() => [] as RoadmapMilestone[]),
        ]);
        setRoadmap(rm);
        setItems(its);
        setMilestones(ms);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "";
        if (msg.includes("404") || msg.toLowerCase().includes("no roadmap")) {
          setRoadmap(null);
          setItems([]);
          setMilestones([]);
        } else if (msg.includes("503")) {
          throw e;
        } else {
          // For other errors, keep roadmap null but not fatal if analysis exists
          setRoadmap(null);
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load roadmap";
      if (msg.includes("503")) {
        setError("Roadmap tables not configured — run backend/supabase/006_roadmap.sql");
      } else if (msg.includes("401")) {
        setError("Session expired. Please log in again.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAll();
  }, []);

  const handleGenerate = async () => {
    if (!analysis) {
      setError("Run your INAURA analysis first to generate a personalized roadmap.");
      return;
    }
    if (!profile?.hours_per_week) {
      setError("Update your weekly availability to create a realistic timeline. Set hours_per_week in profile (1-80).");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const target = analysis.target_role;
      const result = await generateRoadmap(target);
      setRoadmap(result as Roadmap);
      // After generate, reload full
      await loadAll();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to generate roadmap";
      if (msg.toLowerCase().includes("hours_per_week") || msg.toLowerCase().includes("weekly availability")) {
        setError("Update your weekly availability to create a realistic timeline. Edit profile → hours per week (1-80).");
      } else if (msg.toLowerCase().includes("meeting the assessed") || msg.toLowerCase().includes("no priority gaps")) {
        setError("You're currently meeting the assessed requirements for this role. Keep building evidence and stay industry-ready.");
      } else if (msg.toLowerCase().includes("no analysis")) {
        setError("Run your INAURA analysis first to generate a personalized roadmap.");
      } else if (msg.includes("503")) {
        setError("Roadmap tables not configured — run backend/supabase/006_roadmap.sql");
      } else {
        setError(msg);
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleUpdateItem = async (item: RoadmapItem, patch: { status?: RoadmapItem["status"]; completion_percentage?: number }) => {
    setUpdating(item.id);
    try {
      const updated = await updateRoadmapItem(item.id, patch);
      setItems((prev) => prev.map((p) => (p.id === item.id ? { ...p, ...updated } : p)));
      // Also reload roadmap progress
      try {
        const rm = await getLatestRoadmap();
        setRoadmap(rm);
      } catch {
        // ignore
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update item");
    } finally {
      setUpdating(null);
    }
  };

  const toggleExpand = (id: string) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  if (loading) {
    return (
      <div className="roadmap">
        <div className="container" style={{ padding: "4rem 0", textAlign: "center", color: "#64748b" }}>
          Loading your INAURA roadmap…
        </div>
      </div>
    );
  }

  // Empty states
  if (!analysis) {
    return (
      <div className="roadmap">
        <div className="container" style={{ padding: "2rem 0" }}>
          <div className="roadmap__empty">
            <h2>Run your INAURA analysis first to generate a personalized roadmap.</h2>
            <p>Your roadmap is built from your actual skill gaps and highest-priority gaps — not a generic template.</p>
            <div style={{ marginTop: 16, display: "flex", gap: 8, justifyContent: "center" }}>
              <Link to="/analysis">
                <Button variant="primary" size="md">
                  Go to Analysis
                </Button>
              </Link>
              <Link to="/dashboard">
                <Button variant="secondary" size="md">
                  Dashboard
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!profile?.hours_per_week) {
    return (
      <div className="roadmap">
        <div className="container" style={{ padding: "2rem 0" }}>
          <div className="roadmap__empty">
            <h2>Update your weekly availability to create a realistic timeline.</h2>
            <p>INAURA uses your available hours per week to estimate weeks. Please update your profile.</p>
            <div style={{ marginTop: 16, display: "flex", gap: 8, justifyContent: "center" }}>
              <Link to="/profile/setup">
                <Button variant="primary" size="md">
                  Edit Profile
                </Button>
              </Link>
            </div>
            {roadmap && (
              <div style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: "0.95rem", color: "#475569" }}>You have an existing roadmap:</h3>
                <div style={{ marginTop: 8 }}>
                  <Link to="/roadmap" onClick={(e) => { e.preventDefault(); loadAll(); }}>
                    <Button variant="secondary" size="sm" onClick={loadAll}>
                      Reload
                    </Button>
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  const readinessPct = analysis ? Math.round(analysis.readiness_score * 100) : 0;
  const gapCount = analysis?.gap_count ?? 0;

  const progress = roadmap?.progress ?? (items.length ? Math.round(items.reduce((s, it) => s + (it.completion_percentage || 0), 0) / items.length) : 0);

  const getPriorityLabel = (p: number) => {
    if (p >= 50) return { label: "Critical", cls: "priority--critical" };
    if (p >= 25) return { label: "High", cls: "priority--high" };
    if (p >= 10) return { label: "Medium", cls: "priority--medium" };
    if (p > 0) return { label: "Low", cls: "priority--low" };
    return { label: "Covered", cls: "priority--covered" };
  };

  return (
    <div className="roadmap">
      <header className="roadmap__header">
        <div className="container">
          <Link to="/analysis/results" className="roadmap__back">
            ← Back to Analysis Results
          </Link>
          <div className="eyebrow" style={{ marginTop: 12 }}>
            INAURA Personalized Roadmap — {roadmap?.engine_version || "4D-v1"}
          </div>
          <h1 className="roadmap__title">Your Personalized Roadmap</h1>
          <p className="roadmap__subtitle">Built from your current skill evidence and highest-priority gaps.</p>
          {roadmap && (
            <div className="roadmap__meta">
              <span>
                Target Role: <strong>{roadmap.target_role}</strong>
              </span>
              <span>·</span>
              <span>
                {roadmap.total_estimated_hours}h total · {roadmap.estimated_weeks} weeks at {profile.hours_per_week}h/week
              </span>
            </div>
          )}
        </div>
      </header>

      <main className="container roadmap__main">
        {error && (
          <div className="roadmap__error" role="alert">
            {error}
          </div>
        )}

        {/* Readiness context */}
        <section className="roadmap__card roadmap__card--primary">
          <div className="roadmap__context-grid">
            <div>
              <div className="roadmap__label">Career Readiness</div>
              <div className="roadmap__big">{readinessPct}%</div>
              <div className="roadmap__hint">From latest analysis — {analysis.engine_version}</div>
            </div>
            <div>
              <div className="roadmap__label">Priority Gaps</div>
              <div className="roadmap__big" style={{ color: "#dc2626" }}>
                {gapCount}
              </div>
              <div className="roadmap__hint">Skills below required level</div>
            </div>
            <div>
              <div className="roadmap__label">Estimated Weeks</div>
              <div className="roadmap__big" style={{ color: "#0f766e" }}>
                {roadmap ? roadmap.estimated_weeks : "—"}
              </div>
              <div className="roadmap__hint">{profile.hours_per_week}h/week</div>
            </div>
            <div>
              <div className="roadmap__label">Progress</div>
              <div className="roadmap__big">{roadmap ? `${Math.round(progress)}%` : "0%"}</div>
              <div className="roadmap__hint">Avg completion across items</div>
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: "0.78rem", color: "#64748b" }}>
            Heuristic prototype — not scientifically validated. Based on available evidence and gap priority (gap × importance × demand × confidence × interview).
          </div>
        </section>

        {/* Generate CTA if no roadmap */}
        {!roadmap ? (
          <section className="roadmap__empty">
            <h2>Generate your personalized roadmap.</h2>
            <p>INAURA will create 3–6 prioritized items from your highest-priority gaps, with curated resources and practical projects.</p>
            <div style={{ marginTop: 12 }}>
              <Button variant="primary" size="lg" onClick={handleGenerate} disabled={generating}>
                {generating ? "Generating…" : `Generate Roadmap for ${analysis.target_role}`}
              </Button>
            </div>
            <div style={{ marginTop: 8, fontSize: "0.84rem", color: "#64748b" }}>
              Deterministic — sorted by gap priority, no LLM decisions. Resources are curated prototype resources.
            </div>
          </section>
        ) : (
          <>
            {/* Milestones */}
            <section className="roadmap__section">
              <h2>Milestones</h2>
              <p>Grouped progression — from foundations to industry readiness.</p>
              <div className="roadmap__milestones">
                {milestones.map((m) => {
                  // Compute progress for milestone group
                  const groupItems = items.filter((_, idx) => {
                    const n = items.length;
                    const numM = milestones.length || 1;
                    const per = Math.ceil(n / numM);
                    const start = (m.sequence_order - 1) * per;
                    const end = Math.min(start + per, n);
                    return idx >= start && idx < end;
                  });
                  const mProgress = groupItems.length ? Math.round(groupItems.reduce((s, it) => s + (it.completion_percentage || 0), 0) / groupItems.length) : 0;
                  return (
                    <div key={m.id} className="roadmap__milestone">
                      <div className="roadmap__milestone-head">
                        <strong>
                          {m.sequence_order}. {m.title}
                        </strong>
                        <span className={`status status--${m.status}`}>{m.status.replace("_", " ")}</span>
                      </div>
                      <p style={{ fontSize: "0.86rem", color: "#475569", marginTop: 4 }}>{m.description}</p>
                      <div style={{ marginTop: 8, fontSize: "0.82rem", color: "#64748b" }}>
                        {m.target_hours}h · {groupItems.length} item(s) · Progress {mProgress}%
                      </div>
                      <div className="roadmap__progress-bar">
                        <div className="roadmap__progress-fill" style={{ width: `${mProgress}%` }} />
                      </div>
                    </div>
                  );
                })}
                {milestones.length === 0 && <div style={{ color: "#64748b" }}>No milestones — roadmap has no items.</div>}
              </div>
            </section>

            {/* Roadmap Items */}
            <section className="roadmap__section">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h2>Roadmap Items</h2>
                <Button variant="secondary" size="sm" onClick={handleGenerate} disabled={generating}>
                  {generating ? "Regenerating…" : "Regenerate"}
                </Button>
              </div>
              <p>Priority ordered — high gap × importance × demand × confidence × interview. Each item explains why it matters.</p>
              <div className="roadmap__items">
                {items.map((it) => {
                  const skillName = it.skills?.display_name || it.skills?.canonical_name || it.title;
                  const prio = getPriorityLabel(it.priority);
                  const isExpanded = !!expanded[it.id];
                  return (
                    <div key={it.id} className="roadmap__item">
                      <div className="roadmap__item-head">
                        <div>
                          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <span className="roadmap__seq">{it.sequence_order}</span>
                            <strong>{it.title}</strong>
                            <span className={`priority ${prio.cls}`}>{prio.label}</span>
                            <span style={{ fontSize: "0.78rem", color: "#64748b" }}>{it.item_type}</span>
                          </div>
                          <div style={{ fontSize: "0.84rem", color: "#475569", marginTop: 4 }}>
                            Skill: <strong>{skillName}</strong> {it.skills?.category && <span style={{ color: "#64748b" }}>· {it.skills.category}</span>} · {it.estimated_hours}h
                          </div>
                          <div style={{ fontSize: "0.84rem", color: "#334155", marginTop: 6, background: "#f8fafc", padding: 8, borderRadius: 8 }}>
                            <strong>Why this?</strong> {it.why_it_matters}
                          </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
                          <span className={`status status--${it.status}`}>{it.status.replace("_", " ")}</span>
                          <span style={{ fontSize: "0.82rem", color: "#64748b" }}>{Math.round(it.completion_percentage)}%</span>
                        </div>
                      </div>

                      <div className="roadmap__item-controls">
                        <select
                          value={it.status}
                          onChange={(e) => handleUpdateItem(it, { status: e.target.value as RoadmapItem["status"] })}
                          disabled={updating === it.id}
                          className="roadmap__select"
                        >
                          <option value="not_started">Not started</option>
                          <option value="in_progress">In progress</option>
                          <option value="completed">Completed</option>
                        </select>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={it.completion_percentage}
                          onChange={(e) => handleUpdateItem(it, { completion_percentage: Number(e.target.value) })}
                          disabled={updating === it.id}
                          style={{ width: 140 }}
                        />
                        <span style={{ fontSize: "0.82rem", minWidth: 40 }}>{Math.round(it.completion_percentage)}%</span>
                      </div>

                      <div className="roadmap__progress-bar">
                        <div className="roadmap__progress-fill" style={{ width: `${it.completion_percentage}%` }} />
                      </div>

                      <button type="button" className="roadmap__toggle" onClick={() => toggleExpand(it.id)}>
                        {isExpanded ? "Hide details ▲" : "Show details — resources, practice, project ▼"}
                      </button>

                      {isExpanded && (
                        <div className="roadmap__details">
                          <p style={{ fontSize: "0.86rem", color: "#334155", lineHeight: 1.6 }}>{it.description}</p>
                          {it.roadmap_resources && it.roadmap_resources.length > 0 && (
                            <div style={{ marginTop: 12 }}>
                              <h4 style={{ fontSize: "0.9rem", marginBottom: 6 }}>Curated prototype resources (1–3 per item)</h4>
                              <div className="roadmap__resources">
                                {it.roadmap_resources.map((r) => (
                                  <div key={r.id} className="roadmap__resource">
                                    <div style={{ fontWeight: 600, fontSize: "0.86rem" }}>
                                      <a href={r.url} target="_blank" rel="noreferrer" style={{ color: "#4f46e5" }}>
                                        {r.title}
                                      </a>
                                      <span style={{ marginLeft: 6, fontSize: "0.76rem", background: r.is_free ? "#dcfce7" : "#fef3c7", padding: "2px 6px", borderRadius: 4 }}>
                                        {r.is_free ? "Free" : "Paid"}
                                      </span>
                                      <span style={{ marginLeft: 6, fontSize: "0.76rem", color: "#64748b" }}>{r.resource_type}</span>
                                    </div>
                                    <div style={{ fontSize: "0.82rem", color: "#475569" }}>
                                      {r.provider} · {r.difficulty || "all levels"} {r.estimated_hours ? `· ${r.estimated_hours}h` : ""}
                                    </div>
                                    <div style={{ fontSize: "0.82rem", color: "#64748b", marginTop: 2 }}>{r.description}</div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          <div style={{ marginTop: 10, fontSize: "0.8rem", color: "#64748b" }}>
                            Skill: {skillName} · Priority {it.priority} · Sequence {it.sequence_order} · Curated prototype resources — not live recommendations.
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Overall progress */}
            <section className="roadmap__section">
              <h2>Progress</h2>
              <div style={{ background: "#f1f5f9", borderRadius: 12, padding: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem", color: "#334155" }}>
                  <span>Overall completion</span>
                  <span style={{ fontWeight: 700 }}>{Math.round(progress)}%</span>
                </div>
                <div className="roadmap__progress-bar" style={{ marginTop: 8, height: 10 }}>
                  <div className="roadmap__progress-fill" style={{ width: `${progress}%`, height: 10 }} />
                </div>
                <div style={{ marginTop: 6, fontSize: "0.82rem", color: "#64748b" }}>Derived as average(completion_percentage) — frontend cannot fake overall progress.</div>
              </div>
            </section>
          </>
        )}

        <section className="roadmap__next">
          <h3>How INAURA built this</h3>
          <p style={{ fontSize: "0.86rem", color: "#475569", lineHeight: 1.6 }}>
            Gaps with zero gap are excluded. Remaining gaps are sorted by gap priority (100 × gap × importance × demand × confidence × interview_relevance) — no competing formula. Top 3–6 gaps become roadmap items with Learn → Practice → Build → Validate progression relevant to the skill. Total hours are heuristic (small learn 3h, practice 4h, project 10–18h, assessment 3h) and estimated weeks = ceil(total_hours / hours_per_week). Resources are curated prototype resources, not scraped.
          </p>
          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
            <Link to="/analysis/results">
              <Button variant="secondary" size="md">
                View Analysis Results
              </Button>
            </Link>
            <Link to="/dashboard">
              <Button variant="secondary" size="md">
                Dashboard
              </Button>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
