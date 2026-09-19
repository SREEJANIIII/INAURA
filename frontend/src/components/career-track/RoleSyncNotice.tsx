import { useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { getRoleSync, resetRoleSync, subscribeRoleSync } from "../../lib/roleSync";

/**
 * Says what's happening while INAURA catches your analysis and roadmap up to a
 * newly chosen career, or re-runs an out-of-date analysis. Shows nothing when
 * there's nothing to say.
 */
export default function RoleSyncNotice() {
  const sync = useSyncExternalStore(subscribeRoleSync, getRoleSync);
  if (sync.stage === "idle" || !sync.role) return null;

  const busy = sync.stage === "analysing" || sync.stage === "building";

  return (
    <div className={`ct-sync ct-sync--${sync.stage}`} role="status">
      {busy && <span className="ct-sync__spin" aria-hidden="true" />}
      <p>
        {sync.stage === "analysing" && (
          <>
            Re-reading your evidence against <strong>{sync.role}</strong>. This usually takes under a minute — you can
            keep looking around.
          </>
        )}
        {sync.stage === "building" && (
          <>
            Building your new weekly plan for <strong>{sync.role}</strong>…
          </>
        )}
        {sync.stage === "done" && (sync.message ?? (sync.reason === "refresh" ? (
          <>
            Your readiness for <strong>{sync.role}</strong> now reflects your current evidence.
          </>
        ) : (
          <>
            Your analysis and roadmap are now for <strong>{sync.role}</strong>.
          </>
        )))}
        {sync.stage === "failed" && sync.message}
      </p>
      {sync.stage === "done" && !sync.message && sync.reason === "role" && (
        <Link to="/roadmap" className="ct-sync__link">See your plan</Link>
      )}
      {!busy && (
        <button type="button" className="ct-sync__close" onClick={resetRoleSync} aria-label="Dismiss">
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </div>
  );
}
