import { useEffect, useState, useSyncExternalStore } from "react";
import IndustryIntelligence from "../components/analysis/IndustryIntelligence";
import {
  analysisStateData,
  evidencePageData,
  profileData,
  roleCatalogData,
  subscribePageData,
} from "../lib/pageData";
import "../components/analysis/AnalysisPage.css";

export default function Industry() {
  const catalog = useSyncExternalStore(subscribePageData, roleCatalogData.peek);
  const profile = useSyncExternalStore(subscribePageData, profileData.peek);
  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);

  // The catalog is usually preloaded after login; fetch on demand otherwise
  useEffect(() => {
    if (roleCatalogData.peek()) return;
    roleCatalogData
      .fetch()
      .catch((e: unknown) =>
        setCatalogError(e instanceof Error ? e.message : "Role catalog could not be loaded.")
      );
  }, []);
  useEffect(() => {
    if (profileData.peek()) return;
    profileData.fetch().catch(() => undefined);
  }, []);

  const targetRole = (analysisState ?? evidence?.analysisState)?.target_role ?? null;
  const roles = catalog ?? [];
  const activeRole =
    role ??
    (targetRole && roles.some((r) => r.title === targetRole) ? targetRole : (roles[0]?.title ?? null));

  return (
    <div className="an">
      <div className="an__inner">
        <section className="an-sec" aria-labelledby="ind-title">
          <header className="an-sec__head">
            <h1 id="ind-title">Industry intelligence</h1>
            <p>
              What roles require right now — required proficiency, demand, and rising skills.
              Benchmarks from O*NET and ESCO; dynamic overlays are labelled, never live data.
            </p>
          </header>

      {catalogError ? (
        <p className="an-empty">{catalogError}</p>
      ) : roles.length === 0 ? (
        <div className="an-skel an-skel--block" aria-label="Loading roles" />
      ) : (
        <>
          <div className="an-overview__bar" style={{ marginBottom: "1rem" }}>
            <label className="an-faint" htmlFor="industry-role">
              Role
            </label>
            <select
              id="industry-role"
              value={activeRole ?? ""}
              onChange={(e) => setRole(e.target.value || null)}
              style={{ maxWidth: 320 }}
            >
              {roles.map((r) => (
                <option key={r.slug || r.title} value={r.title}>
                  {r.title}
                </option>
              ))}
            </select>
          </div>
          {activeRole && (
            <IndustryIntelligence
              role={activeRole}
              preferredLocation={profile?.preferred_work_location}
            />
          )}
        </>
      )}
        </section>
      </div>
    </div>
  );
}
