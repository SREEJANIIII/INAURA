import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listApplications, listPlacements } from "../../services/outcomes";

/**
 * Career activity summary for the student Career Track sidebar.
 * Derived client-side from the canonical applications + placements lists
 * (no duplicate analytics logic, no new endpoints).
 */
export default function CareerActivity() {
  const [counts, setCounts] = useState({ applications: 0, interviews: 0, offers: 0, selected: 0, joined: 0 });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([listApplications(), listPlacements()]).then(([appsRes, placeRes]) => {
      if (!alive) return;
      const apps = appsRes.status === "fulfilled" ? appsRes.value : [];
      const placements = placeRes.status === "fulfilled" ? placeRes.value : [];
      const inStatus = (s: string) => apps.filter((a) => a.status === s).length;
      setCounts({
        applications: apps.length,
        interviews: inStatus("interview"),
        offers: inStatus("offer_received"),
        selected: inStatus("selected"),
        joined: placements.filter((p) => p.status === "joined").length,
      });
      setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!loaded) return null;
  if (counts.applications === 0) return null;

  const rows: Array<[string, number]> = [
    ["Applications", counts.applications],
    ["Interviews", counts.interviews],
    ["Offers", counts.offers],
    ["Selected", counts.selected],
    ["Joined", counts.joined],
  ];

  return (
    <section className="ct-block" aria-label="Career activity">
      <div className="ct-block__head">
        <h2 className="ct-block__title">Career activity</h2>
        <Link to="/applications" className="ct-link">
          View applications
        </Link>
      </div>
      <ul className="ct-sources">
        {rows.map(([label, n]) => (
          <li key={label}>
            <span className="ct-source">
              <span className="ct-source__label">{label}</span>
              <span className="ct-source__detail ct-num">{n}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
