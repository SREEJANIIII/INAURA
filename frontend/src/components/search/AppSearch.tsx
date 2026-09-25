import { useMemo, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";
import {
  analysisStateData,
  capabilityMapData,
  evidencePageData,
  resultsPageData,
  roadmapPageData,
  roleCatalogData,
  subscribePageData,
} from "../../lib/pageData";
import { displayName, findRole, roleId, toId } from "../career-track/careerTrackModel";
import SearchBar from "./SearchBar";
import { buildIndex, search, type SearchResult } from "./searchIndex";

/**
 * The top bar's search, joined up to whatever the app has already loaded.
 *
 * It searches in the browser over data the pages fetched anyway, so results appear as you
 * type with nothing to wait for. Whatever hasn't loaded yet simply isn't in the results yet.
 */
export default function AppSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const catalog = useSyncExternalStore(subscribePageData, roleCatalogData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const results = useSyncExternalStore(subscribePageData, resultsPageData.peek);
  const roadmap = useSyncExternalStore(subscribePageData, roadmapPageData.peek);
  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);

  // Skills come from the career track you're on, which is the role you're aiming for
  const targetTitle = (analysisState ?? evidence?.analysisState)?.target_role ?? null;
  const role = catalog && targetTitle ? findRole(catalog, toId(targetTitle)) : undefined;
  const mapEntry = role ? capabilityMapData(role.title) : null;
  const map = useSyncExternalStore(subscribePageData, () => mapEntry?.peek());

  const index = useMemo(
    () =>
      buildIndex({
        roles: catalog?.map((r) => ({ id: roleId(r), title: r.title, description: r.description })),
        careerId: role ? roleId(role) : undefined,
        skills: map?.skills.map((s) => ({
          id: toId(s.slug || s.skill),
          name: displayName(s.skill),
          category: s.category,
        })),
        gaps: results?.gaps.map((g) => ({ skill: displayName(g.canonical_name || g.skill || "") })).filter((g) => g.skill),
        projects: evidence?.projects.map((p) => ({ id: p.id, name: p.name, technologies: p.technologies })),
        certificates: evidence?.certs.map((c) => ({ id: c.id, name: c.name, issuer: c.issuing_org })),
        resources: roadmap?.weeks.flatMap((w) =>
          (w.tasks ?? []).flatMap((t) =>
            (t.resources ?? []).map((r, i) => ({ id: `${t.id}-${i}`, title: r.title, skill: t.skill_name }))
          )
        ),
        weeks: roadmap?.weeks.map((w) => ({
          id: w.id,
          number: w.week_number,
          title: w.title,
          tasks: w.tasks?.map((t) => ({ id: t.id, title: t.title, skill: t.skill_name })),
        })),
      }),
    [catalog, role, map, results, evidence, roadmap]
  );

  const matches = useMemo(() => search(query, index), [query, index]);

  const go = (result: SearchResult) => {
    navigate(result.to);
    // Following a link to a section of the page you're already on won't move it by itself
    const [, hash] = result.to.split("#");
    if (hash) requestAnimationFrame(() => document.getElementById(hash)?.scrollIntoView({ block: "start" }));
  };

  return <SearchBar onQueryChange={setQuery} results={matches} onSelect={go} />;
}
