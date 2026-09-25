import { useEffect, useState } from "react";
import { getRoleIntelligence, type IntelligenceResponse } from "../../services/industry";

const pct = (v: number) => Math.round((v ?? 0) * 100);
const titleCase = (v?: string | null) => v ? v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Unknown";
const originLabel = (v?: string | null) => v === "demo_seeded" ? "Dynamic / Demo Seed" : v === "source_data" ? "Baseline source data" : v === "inaura_derived" ? "INAURA-derived" : "Unknown origin";
const demandWord = (v: number) => v >= .85 ? "High" : v >= .70 ? "Solid" : v >= .50 ? "Moderate" : "Low";
const dateLabel = (v?: string | null) => { if (!v) return null; const d = new Date(v); return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }); };

export default function IndustryIntelligence({ role, preferredLocation }: { role: string; preferredLocation?: string | null }) {
  const [data, setData] = useState<IntelligenceResponse | null>(null);
  const [location, setLocation] = useState(preferredLocation?.trim() || "");
  const [appliedLocation, setAppliedLocation] = useState<string | undefined>(preferredLocation?.trim() || undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const next = preferredLocation?.trim() || undefined;
    setLocation(next || "");
    setAppliedLocation(next);
  }, [preferredLocation]);
  useEffect(() => { let cancelled = false; setLoading(true); setError(null); getRoleIntelligence(role, appliedLocation).then((r) => { if (!cancelled) { setData(r); setLoading(false); } }).catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : "Industry intelligence could not be loaded."); setLoading(false); } }); return () => { cancelled = true; }; }, [role, appliedLocation]);
  if (loading) return <div className="an-skel an-skel--block" aria-label="Loading industry intelligence" />;
  if (error || !data) return <p className="an-empty">{error ?? "Industry intelligence is not available for this role yet."}</p>;
  const top = data.skills.slice(0, 8), rising = data.skills.filter((s) => s.trend === "rising" || s.trend === "emerging"), hasDemo = (data.data_origins ?? []).includes("demo_seeded");
  const requestedLocation = appliedLocation || "Global";
  return <div>
    <div className="an-overview__bar"><span><strong>Target role: {data.role}</strong><span className="an-faint"> · Target location: {requestedLocation}</span></span><form onSubmit={(e) => { e.preventDefault(); setAppliedLocation(location.trim() || undefined); }} style={{ display: "flex", gap: 8, alignItems: "center" }}><label className="an-faint" htmlFor="intel-location">Location</label><input id="intel-location" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Bengaluru (optional)" style={{ maxWidth: 220 }} /><button type="submit" className="an-link an-link--btn">Apply</button></form></div>
    <p className="an-note"><strong>Baseline industry knowledge:</strong> O*NET and ESCO provide structured occupation and skills benchmarks.<br /><strong>Dynamic industry signals:</strong> demand, trend, location, and freshness overlays are shown separately and are not live data.</p>
    {data.location_match === "fallback_global" && appliedLocation && <p className="an-note"><strong>Using global baseline — location-specific data unavailable.</strong> No city-specific demand was fabricated for {appliedLocation}.</p>}
    {rising.length > 0 && <p className="an-note">Rising / emerging: {rising.map((s) => s.skill).join(", ")}</p>}
    <ul className="an-skills">{top.map((s) => <li key={`${s.skill}-${s.source_concept ?? ""}`} className="an-skill"><div className="an-skill__row"><span className="an-skill__name">{s.skill}{s.skill_category && <span className="an-faint">{s.skill_category}</span>}</span><span className="an-cmp an-cmp--lg" aria-label={`${s.skill}: required ${pct(s.required_level)}%, demand ${demandWord(s.demand)}`}><span className="an-cmp__you" style={{ width: `${pct(s.required_level)}%` }} /></span><span className="an-skill__nums an-num"><span>Req {pct(s.required_level)}</span><span className="an-faint">{demandWord(s.demand)}</span></span>{(s.trend === "rising" || s.trend === "emerging") && <span className="an-skill__status">{titleCase(s.trend)}</span>}</div><div className="an-skill__detail" style={{ display: "block" }}><dl className="an-facts"><div><dt>Required proficiency</dt><dd className="an-num">{pct(s.required_level)}%</dd></div><div><dt>Demand</dt><dd>{demandWord(s.demand)} <span className="an-faint">({pct(s.demand)}%)</span></dd></div><div><dt>Importance</dt><dd className="an-num">{pct(s.importance)}%</dd></div><div><dt>Trend</dt><dd>{titleCase(s.trend)}</dd></div><div><dt>Freshness</dt><dd>{titleCase(s.freshness)}{dateLabel(s.collected_at || s.last_updated || s.retrieved_at) ? ` · updated ${dateLabel(s.collected_at || s.last_updated || s.retrieved_at)}` : ""}</dd></div><div><dt>Source</dt><dd>{s.source || "Unknown source"} <span className="an-faint">· {originLabel(s.data_origin)}</span>{s.source_url && <><br /><a href={s.source_url} target="_blank" rel="noreferrer">View source</a></>}</dd></div>{s.mapping_status === "unmapped" && <div><dt>External concept</dt><dd>{s.source_concept || s.skill} <span className="an-faint">· preserved, unmapped</span></dd></div>}{s.evidence_context && <div><dt>Evidence context</dt><dd>{s.evidence_context}</dd></div>}</dl></div></li>)}</ul>
    <p className="an-note">Data origins: O*NET · ESCO · {(data.data_origins ?? []).map(originLabel).join(" · ") || "benchmarks"}</p>{hasDemo && <p className="an-note">Dynamic / Demo Seed overlays are deterministic plumbing examples, not verified real-time market data.</p>}{data.note && <p className="an-note">{data.note}</p>}
  </div>;
}
