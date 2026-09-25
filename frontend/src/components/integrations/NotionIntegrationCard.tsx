import { useEffect, useState, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Button from "../ui/app-button";
import {
  getNotionStatus,
  getNotionConnectUrl,
  syncNotion,
  disconnectNotion,
  setNotionPageExcluded,
  type NotionStatus,
  type NotionSyncResult,
  type NotionSyncedPage,
  type NotionEvidenceItem,
} from "../../services/notion";
import { refreshPageData } from "../../lib/pageData";
import { friendlyError } from "../../lib/errors";
import "./NotionIntegrationCard.css";

type Banner = { type: "success" | "error" | "info"; message: string };

const OAUTH_ERRORS: Record<string, string> = {
  access_denied: "Notion authorization was denied. You can connect any time you’re ready.",
  invalid_state: "That sign-in link expired before it finished. Please connect again.",
  missing_code_or_state: "Notion didn’t send back everything INAURA needs. Please connect again.",
  token_exchange_failed: "Notion couldn’t confirm the connection. Please try again.",
  missing_access_token: "Notion didn’t grant access. Please try again.",
};

/** What the return trip from Notion's consent screen reported, in the address */
function bannerFromOAuth(search: string): Banner | null {
  const params = new URLSearchParams(search);
  if (params.get("notion") === "connected") {
    return { type: "success", message: "Notion connected. Sync your pages to add them as evidence." };
  }
  const code = params.get("notion_error");
  if (!code) return null;
  // Only known codes are shown; the address is not a place to take wording from
  return { type: "error", message: OAUTH_ERRORS[code] ?? "Notion didn’t finish connecting. Please try again." };
}

interface NotionIntegrationCardProps {
  onSyncComplete?: () => void;
  onDisconnectComplete?: () => void;
  className?: string;
}

const TIER_META: Record<
  string,
  { label: string; icon: string; tone: string; desc: string }
> = {
  demonstrated: {
    label: "Demonstrated",
    icon: "🚀",
    tone: "demonstrated",
    desc: "Production code, benchmarks, test suites",
  },
  implemented: {
    label: "Implemented",
    icon: "🛠️",
    tone: "implemented",
    desc: "Working code samples, components, schemas",
  },
  practiced: {
    label: "Practiced",
    icon: "✍️",
    tone: "practiced",
    desc: "Solved exercises, tutorials, practice checklists",
  },
  studied: {
    label: "Studied",
    icon: "📖",
    tone: "studied",
    desc: "Conceptual notes, architecture outlines, guides",
  },
  mentioned: {
    label: "Mentioned",
    icon: "📌",
    tone: "mentioned",
    desc: "Keywords, reading list, introductory references",
  },
};

export default function NotionIntegrationCard({
  onSyncComplete,
  onDisconnectComplete,
  className = "",
}: NotionIntegrationCardProps) {
  const [status, setStatus] = useState<NotionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [syncingStep, setSyncingStep] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<NotionSyncResult | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  // Coming back from Notion's consent screen, the address says how it went
  const [banner, setBanner] = useState<Banner | null>(() => bannerFromOAuth(location.search));
  const [showPrivacy, setShowPrivacy] = useState(false);

  // View & filtering states
  const [activeTab, setActiveTab] = useState<"pages" | "signals">("pages");
  const [searchQuery, setSearchQuery] = useState("");
  const [skillFilter, setSkillFilter] = useState("all");
  const [depthFilter, setDepthFilter] = useState("all");
  const [expandedPageIds, setExpandedPageIds] = useState<Set<string>>(new Set());
  const [togglingPageIds, setTogglingPageIds] = useState<Set<string>>(new Set());

  const loadStatus = async () => {
    try {
      const data = await getNotionStatus();
      setStatus(data);
    } catch {
      // The card still offers to connect; a failed status check isn't worth an alarm
    } finally {
      setLoading(false);
    }
  };

  // Once, when the card opens
  useEffect(() => {
    let alive = true;
    getNotionStatus()
      .then((data) => alive && setStatus(data))
      .catch(() => undefined)
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // The OAuth result has been read into the banner; take it out of the address so a refresh
  // doesn't announce it again
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (!params.has("notion") && !params.has("notion_error")) return;
    params.delete("notion");
    params.delete("notion_error");
    navigate({ search: params.toString(), hash: location.hash }, { replace: true });
  }, [location.search, location.hash, navigate]);

  const handleConnect = async () => {
    try {
      setConnecting(true);
      setBanner(null);
      const authUrl = await getNotionConnectUrl();
      window.location.href = authUrl;
    } catch (err) {
      setConnecting(false);
      setBanner({
        type: "error",
        message: friendlyError(err, "Notion couldn’t be reached to start connecting. Please try again."),
      });
    }
  };

  const handleSync = async () => {
    try {
      setBanner(null);
      setSyncResult(null);
      setSyncingStep("Scanning authorized Notion workspace...");
      await new Promise((r) => setTimeout(r, 400));

      setSyncingStep("Extracting technical concepts & code samples...");
      const result = await syncNotion();

      setSyncingStep("Updating your INAURA skill profile...");
      setSyncResult(result);
      await loadStatus();
      refreshPageData();
      if (onSyncComplete) onSyncComplete();

      setTimeout(() => {
        setSyncingStep(null);
      }, 2500);
    } catch (err) {
      setSyncingStep(null);
      setBanner({
        type: "error",
        message: friendlyError(err, "Your Notion pages couldn’t be synced. Check your connection and try again."),
      });
    }
  };

  const handleDisconnect = async () => {
    try {
      setDisconnecting(true);
      await disconnectNotion();
      setShowDisconnectModal(false);
      await loadStatus();
      setBanner({
        type: "info",
        message: "Notion has been disconnected and associated Notion evidence removed.",
      });
      refreshPageData();
      if (onDisconnectComplete) onDisconnectComplete();
    } catch (err) {
      setBanner({
        type: "error",
        message: friendlyError(err, "Notion couldn’t be disconnected. Please try again."),
      });
    } finally {
      setDisconnecting(false);
    }
  };

  const toggleExpand = (pageId: string) => {
    setExpandedPageIds((prev) => {
      const next = new Set(prev);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      return next;
    });
  };

  const isConnected = status?.connected === true && status.status === "connected";
  const needsReconnect = status?.status === "reconnect_required" || status?.status === "revoked";

  // Synced pages and aggregated evidence items.
  // Excluded pages stay visible as study links but never contribute to scoring.
  const syncedPages: NotionSyncedPage[] = useMemo(() => {
    return status?.synced_pages || syncResult?.synced_pages || [];
  }, [status, syncResult]);

  const includedPages = useMemo(() => {
    return syncedPages.filter((p) => !p.is_excluded);
  }, [syncedPages]);

  const excludedCount = syncedPages.length - includedPages.length;

  const handleTogglePageExclusion = async (page: NotionSyncedPage) => {
    const next = !page.is_excluded;
    setTogglingPageIds((prev) => new Set(prev).add(page.page_id));
    try {
      await setNotionPageExcluded(page.page_id, next);
      await loadStatus();
      refreshPageData();
      setBanner({
        type: "info",
        message: next
          ? `"${page.page_title}" excluded from scoring — kept below as a study link.`
          : `"${page.page_title}" included in scoring again.`,
      });
    } catch (err) {
      setBanner({
        type: "error",
        message: friendlyError(err, "That page’s setting couldn’t be changed. Please try again."),
      });
    } finally {

      setTogglingPageIds((prev) => {
        const nextSet = new Set(prev);
        nextSet.delete(page.page_id);
        return nextSet;
      });
    }
  };

  const allSkills = useMemo(() => {
    const s = new Set<string>();
    includedPages.forEach((p) => {
      (p.skills || []).forEach((sk) => s.add(sk));
    });
    return Array.from(s).sort();
  }, [includedPages]);

  const allEvidenceItems = useMemo(() => {
    const items: NotionEvidenceItem[] = [];
    includedPages.forEach((p) => {
      (p.extracted_evidence || []).forEach((e) => {
        items.push({
          ...e,
          sourcePageTitle: e.sourcePageTitle || p.page_title,
          sourceUrl: e.sourceUrl || p.page_url,
        });
      });
    });
    return items;
  }, [includedPages]);

  // Filtered pages
  const filteredPages = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return syncedPages.filter((p) => {
      const matchQuery =
        !query ||
        p.page_title.toLowerCase().includes(query) ||
        (p.skills || []).some((s) => s.toLowerCase().includes(query)) ||
        (p.headings || []).some((h) => h.toLowerCase().includes(query));

      const matchSkill = skillFilter === "all" || (p.skills || []).includes(skillFilter);

      const matchDepth =
        depthFilter === "all" ||
        (p.extracted_evidence || []).some((e) => e.evidenceType === depthFilter);

      return matchQuery && matchSkill && matchDepth;
    });
  }, [syncedPages, searchQuery, skillFilter, depthFilter]);

  // Filtered evidence items
  const filteredSignals = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return allEvidenceItems.filter((it) => {
      const matchQuery =
        !query ||
        it.skill.toLowerCase().includes(query) ||
        (it.sourcePageTitle || "").toLowerCase().includes(query) ||
        (it.topics || []).some((t) => t.toLowerCase().includes(query)) ||
        (it.excerpt || "").toLowerCase().includes(query);

      const matchSkill = skillFilter === "all" || it.skill === skillFilter;
      const matchDepth = depthFilter === "all" || it.evidenceType === depthFilter;

      return matchQuery && matchSkill && matchDepth;
    });
  }, [allEvidenceItems, searchQuery, skillFilter, depthFilter]);

  return (
    <div className={`notion-card ${className}`}>
      {/* Status Banner */}
      {banner && (
        <div className={`notion-card__status-banner notion-card__status-banner--${banner.type}`}>
          <span>{banner.message}</span>
          <button
            type="button"
            className="notion-card__banner-close"
            onClick={() => setBanner(null)}
            aria-label="Dismiss notice"
          >
            ×
          </button>
        </div>
      )}

      {/* Header */}
      <div className="notion-card__header">
        <div className="notion-card__brand">
          <div className="notion-card__icon" aria-hidden="true">
            N
          </div>
          <div>
            <h3 className="notion-card__title">Notion</h3>
          </div>
        </div>

        {isConnected ? (
          <span className="notion-card__badge notion-card__badge--connected">
            ✓ Connected
          </span>
        ) : needsReconnect ? (
          <span className="notion-card__badge notion-card__badge--warning">
            ⚠ Reconnect Needed
          </span>
        ) : (
          <span className="notion-card__badge" style={{ background: "rgba(0,0,0,0.06)", color: "var(--muted-2)" }}>
            Not Connected
          </span>
        )}
      </div>

      {!isConnected ? (
        <>
          <p className="notion-card__desc">
            Connect your Notion workspace to allow INAURA to analyze technical notes, system design docs,
            code snippets, and practice logs as evidence of your skills.
          </p>

          <div className="notion-card__notice">
            🔒 <strong>Granular Permission Model:</strong> INAURA only reads the specific pages and
            databases that you explicitly select during Notion's OAuth authorization screen.
          </div>

          <div className="notion-card__actions">
            <Button
              variant="primary"
              size="md"
              onClick={handleConnect}
              disabled={connecting || loading}
            >
              {connecting ? "Connecting to Notion..." : "Connect Notion"}
            </Button>
          </div>
        </>
      ) : (
        <>
          {/* Workspace Meta Summary */}
          <div className="notion-card__meta">
            <div className="notion-card__meta-item">
              <span className="notion-card__meta-label">Workspace</span>
              <span className="notion-card__meta-val">
                {status?.workspace_icon ? `${status.workspace_icon} ` : ""}
                {status?.workspace_name || "Authorized Workspace"}
              </span>
            </div>
            <div className="notion-card__meta-item">
              <span className="notion-card__meta-label">Last Synced</span>
              <span className="notion-card__meta-val">
                {status?.last_synced_at
                  ? new Date(status.last_synced_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "Not synced yet"}
              </span>
            </div>
            <div className="notion-card__meta-item">
              <span className="notion-card__meta-label">Pages Scanned</span>
              <span className="notion-card__meta-val">{syncedPages.length}</span>
            </div>
            <div className="notion-card__meta-item">
              <span className="notion-card__meta-label">Skills Detected</span>
              <span className="notion-card__meta-val">{allSkills.length}</span>
            </div>
            <div className="notion-card__meta-item">
              <span className="notion-card__meta-label">Evidence Signals</span>
              <span className="notion-card__meta-val">{allEvidenceItems.length}</span>
            </div>
            {excludedCount > 0 && (
              <div className="notion-card__meta-item">
                <span className="notion-card__meta-label">Excluded from scoring</span>
                <span className="notion-card__meta-val">{excludedCount} page{excludedCount === 1 ? "" : "s"}</span>
              </div>
            )}
          </div>

          {/* Sync in Progress Indicator */}
          {syncingStep && (
            <div className="notion-card__sync-progress" role="status">
              <div className="notion-card__spinner" />
              <span>{syncingStep}</span>
            </div>
          )}

          {/* Personalized Impact Insight */}
          {syncedPages.length > 0 && !syncingStep && (
            <div className="notion-insight">
              <div className="notion-insight__icon">🎯</div>
              <div className="notion-insight__content">
                <strong>Personalized Skill Impact:</strong> Your Notion workspace contributed{" "}
                <strong>{allEvidenceItems.length} verified signals</strong> across{" "}
                <strong>{allSkills.length} skills</strong> (
                {allSkills.slice(0, 5).join(", ")}
                {allSkills.length > 5 ? "…" : ""}). These signals feed directly into your INAURA
                Skill Assessment, increasing confidence ratings and personalizing your roadmap.
                {excludedCount > 0 && (
                  <> Excluded pages ({excludedCount}) stay as study links and don't affect scoring.</>
                )}
              </div>
            </div>
          )}

          {/* Action Bar */}
          <div className="notion-card__actions" style={{ marginBottom: "20px" }}>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSync}
              disabled={!!syncingStep}
            >
              {syncingStep ? "Syncing..." : "Sync Now"}
            </Button>

            <Button
              variant="secondary"
              size="sm"
              onClick={() => window.open("https://www.notion.so/my-integrations", "_blank", "noopener,noreferrer")}
            >
              Manage Access in Notion ↗
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowDisconnectModal(true)}
              style={{ color: "var(--bad-ink)" }}
            >
              Disconnect
            </Button>
          </div>

          {/* Interactive Content Inspection */}
          {syncedPages.length > 0 ? (
            <div>
              {/* Tab Navigation */}
              <div className="notion-tabs">
                <button
                  type="button"
                  className={`notion-tab ${activeTab === "pages" ? "notion-tab--active" : ""}`}
                  onClick={() => setActiveTab("pages")}
                >
                  📑 Fetched Pages ({syncedPages.length})
                </button>
                <button
                  type="button"
                  className={`notion-tab ${activeTab === "signals" ? "notion-tab--active" : ""}`}
                  onClick={() => setActiveTab("signals")}
                >
                  ⚡ Extracted Skills & Proof ({allEvidenceItems.length})
                </button>
              </div>

              {/* Search & Filter Bar */}
              <div className="notion-filter-bar">
                <input
                  type="text"
                  className="notion-filter-search"
                  placeholder={activeTab === "pages" ? "Search pages by title or topic..." : "Search skills or notes..."}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />

                <select
                  className="notion-filter-select"
                  value={skillFilter}
                  onChange={(e) => setSkillFilter(e.target.value)}
                  aria-label="Filter by skill"
                >
                  <option value="all">All Skills ({allSkills.length})</option>
                  {allSkills.map((sk) => (
                    <option key={sk} value={sk}>
                      {sk}
                    </option>
                  ))}
                </select>

                <select
                  className="notion-filter-select"
                  value={depthFilter}
                  onChange={(e) => setDepthFilter(e.target.value)}
                  aria-label="Filter by depth tier"
                >
                  <option value="all">All Depth Levels</option>
                  <option value="demonstrated">Demonstrated (Level 4)</option>
                  <option value="implemented">Implemented (Level 3)</option>
                  <option value="practiced">Practiced (Level 2)</option>
                  <option value="studied">Studied (Level 2)</option>
                  <option value="mentioned">Mentioned (Level 1)</option>
                </select>
              </div>

              {/* Tab 1: Fetched Pages View */}
              {activeTab === "pages" && (
                <div className="notion-pages-list">
                  {filteredPages.length === 0 ? (
                    <div style={{ textAlign: "center", padding: "20px", color: "var(--muted-foreground)" }}>
                      No pages matched your search filter.
                    </div>
                  ) : (
                    filteredPages.map((page) => {
                      const isExpanded = expandedPageIds.has(page.page_id);
                      const pageEv = page.extracted_evidence || [];
                      const isExcluded = !!page.is_excluded;
                      const isToggling = togglingPageIds.has(page.page_id);

                      return (
                        <div
                          key={page.page_id}
                          className="notion-page-card"
                          style={isExcluded ? { opacity: 0.72, borderStyle: "dashed" } : undefined}
                        >
                          <div className="notion-page-card__head">
                            <div className="notion-page-card__info">
                              <span className="notion-page-card__icon" aria-hidden="true">
                                📄
                              </span>
                              <div>
                                <h4 className="notion-page-card__title">
                                  <span>{page.page_title}</span>
                                  {isExcluded && (
                                    <span
                                      className="notion-pill"
                                      title="Excluded from career-readiness scoring; kept as a study link"
                                    >
                                      🚫 Excluded from scoring
                                    </span>
                                  )}
                                  {page.page_url && (
                                    <a
                                      href={page.page_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="notion-page-card__link"
                                    >
                                      Open in Notion ↗
                                    </a>
                                  )}
                                </h4>

                                <div className="notion-page-card__meta-row">
                                  {page.last_edited_time && (
                                    <span>
                                      Edited{" "}
                                      {new Date(page.last_edited_time).toLocaleDateString(undefined, {
                                        month: "short",
                                        day: "numeric",
                                        year: "numeric",
                                      })}
                                    </span>
                                  )}

                                  {page.word_count > 0 && (
                                    <span className="notion-pill">{page.word_count} words</span>
                                  )}

                                  {(page.code_languages || []).map((lang) => (
                                    <span key={lang} className="notion-pill" style={{ textTransform: "capitalize" }}>
                                      {lang}
                                    </span>
                                  ))}
                                </div>

                                <div
                                  style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "8px" }}
                                >
                                  {page.page_url && (
                                    <a
                                      href={page.page_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="notion-page-card__link"
                                      style={{ fontWeight: 700 }}
                                    >
                                      📖 Study this page in Notion ↗
                                    </a>
                                  )}
                                  <button
                                    type="button"
                                    className="notion-page-card__toggle"
                                    onClick={() => handleTogglePageExclusion(page)}
                                    disabled={isToggling}
                                    title={
                                      isExcluded
                                        ? "Include this page in career-readiness scoring"
                                        : "Exclude this page from scoring (e.g. copied notes for future learning)"
                                    }
                                  >
                                    {isToggling
                                      ? "Updating..."
                                      : isExcluded
                                        ? "✓ Include in scoring"
                                        : "🚫 Exclude from scoring"}
                                  </button>
                                </div>
                                {isExcluded && (
                                  <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", marginTop: "6px" }}>
                                    Kept as a study link — its signals don't count toward readiness.
                                  </div>
                                )}
                              </div>
                            </div>

                            <button
                              type="button"
                              className="notion-page-card__toggle"
                              onClick={() => toggleExpand(page.page_id)}
                              aria-expanded={isExpanded}
                            >
                              {isExpanded ? "▴ Hide Proof" : `▾ View Proof (${pageEv.length})`}
                            </button>
                          </div>

                          {/* Skill Chips */}
                          {(page.skills || []).length > 0 && (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "10px" }}>
                              {page.skills.map((sk) => (
                                <span key={sk} className="notion-skill-chip">
                                  {sk}
                                </span>
                              ))}
                            </div>
                          )}

                          {/* Expanded Evidence Details */}
                          {isExpanded && (
                            <div className="notion-page-evidence-box">
                              <span style={{ fontSize: "0.78rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--muted-foreground)" }}>
                                Extracted Evidence Signals ({pageEv.length}):
                              </span>

                              {pageEv.map((ev, idx) => {
                                const meta = TIER_META[ev.evidenceType] || TIER_META.mentioned;
                                const pct = Math.round((ev.confidence || 0.5) * 100);

                                return (
                                  <div key={`${ev.skill}-${idx}`} className="notion-evidence-row">
                                    <div className="notion-evidence-row__top">
                                      <div className="notion-evidence-row__skill">
                                        <span>{ev.skill}</span>
                                        <span className={`notion-tier-badge notion-tier-badge--${meta.tone}`}>
                                          {meta.icon} {meta.label}
                                        </span>
                                      </div>

                                      <div className="notion-confidence-tag">
                                        <div className="notion-confidence-bar">
                                          <div
                                            className="notion-confidence-fill"
                                            style={{ width: `${pct}%` }}
                                          />
                                        </div>
                                        <span>{pct}% confidence</span>
                                      </div>
                                    </div>

                                    {ev.topics && ev.topics.length > 0 && (
                                      <div className="notion-evidence-topics">
                                        <span>Key Concepts:</span>
                                        {ev.topics.map((t) => (
                                          <span key={t} className="notion-topic-pill">
                                            {t}
                                          </span>
                                        ))}
                                      </div>
                                    )}

                                    {ev.excerpt && (
                                      <div className="notion-evidence-excerpt">
                                        "{ev.excerpt}"
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}

              {/* Tab 2: All Extracted Signals View */}
              {activeTab === "signals" && (
                <div className="notion-signals-grid">
                  {filteredSignals.length === 0 ? (
                    <div style={{ textAlign: "center", padding: "20px", color: "var(--muted-foreground)", gridColumn: "1 / -1" }}>
                      No skill signals matched your filter.
                    </div>
                  ) : (
                    filteredSignals.map((sig, idx) => {
                      const meta = TIER_META[sig.evidenceType] || TIER_META.mentioned;
                      const pct = Math.round((sig.confidence || 0.5) * 100);

                      return (
                        <div key={`sig-${sig.skill}-${idx}`} className="notion-signal-card">
                          <div className="notion-signal-card__head">
                            <span style={{ fontWeight: 700, fontSize: "0.95rem" }}>{sig.skill}</span>
                            <span className={`notion-tier-badge notion-tier-badge--${meta.tone}`}>
                              {meta.icon} {meta.label}
                            </span>
                          </div>

                          <div className="notion-confidence-tag">
                            <div className="notion-confidence-bar">
                              <div
                                className="notion-confidence-fill"
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span>{pct}% confidence · {meta.desc}</span>
                          </div>

                          {sig.topics && sig.topics.length > 0 && (
                            <div className="notion-evidence-topics">
                              {sig.topics.map((t) => (
                                <span key={t} className="notion-topic-pill">
                                  {t}
                                </span>
                              ))}
                            </div>
                          )}

                          {sig.excerpt && (
                            <div className="notion-evidence-excerpt">
                              "{sig.excerpt}"
                            </div>
                          )}

                          {sig.sourcePageTitle && (
                            <a
                              href={sig.sourceUrl || "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="notion-signal-card__source"
                            >
                              📄 From: {sig.sourcePageTitle} ↗
                            </a>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="notion-empty-state">
              <div className="notion-empty-state__icon">📝</div>
              <h4 className="notion-empty-state__title">No Notion pages scanned yet</h4>
              <p className="notion-empty-state__desc">
                When you connected Notion, which pages did you authorize? Click <strong>Sync Now</strong> to fetch your
                notes, or click <strong>Manage Access in Notion ↗</strong> to check the pages you shared with INAURA.
              </p>
              <Button variant="primary" size="sm" onClick={handleSync} disabled={!!syncingStep}>
                {syncingStep ? "Scanning..." : "Sync Now"}
              </Button>
            </div>
          )}
        </>
      )}

      {/* Privacy & Permission details */}
      <div className="notion-card__details">
        <button
          type="button"
          className="notion-card__privacy-toggle"
          onClick={() => setShowPrivacy(!showPrivacy)}
          aria-expanded={showPrivacy}
        >
          {showPrivacy ? "Hide access & privacy details" : "How does INAURA use Notion content?"}
        </button>

        {showPrivacy && (
          <div className="notion-card__privacy-content">
            <p>
              <strong>Data Privacy & Scope:</strong>
            </p>
            <ul>
              <li>
                <strong>Authorized Pages Only:</strong> Notion's official OAuth flow requires you to
                select which pages to share. INAURA has zero access to pages you do not explicitly share.
              </li>
              <li>
                <strong>Evidence Extraction:</strong> We inspect your notes for technical concepts studied,
                code snippets written, and exercises completed to provide proof for your skill profile.
              </li>
              <li>
                <strong>No Secrets Shared:</strong> We never request or store your Notion password or session cookies. Access tokens are encrypted at rest on the server.
              </li>
              <li>
                <strong>Full Control:</strong> Disconnecting removes INAURA's access token and deletes all Notion-derived evidence while preserving your GitHub and project evidence.
              </li>
            </ul>
          </div>
        )}
      </div>

      {/* Disconnect Confirmation Modal */}
      {showDisconnectModal && (
        <div className="notion-dialog-overlay" role="dialog" aria-modal="true" aria-labelledby="notion-modal-title">
          <div className="notion-dialog">
            <h4 id="notion-modal-title" className="notion-dialog__title">
              Disconnect Notion?
            </h4>
            <div className="notion-dialog__body">
              <p>Are you sure you want to disconnect your Notion workspace?</p>
              <ul>
                <li>INAURA will permanently delete the stored integration token.</li>
                <li>All Notion-derived learning evidence will be removed from your skill profile.</li>
                <li>Future synchronization will stop immediately.</li>
                <li>
                  <strong>Existing evidence from GitHub, projects, resume, and certifications will remain untouched.</strong>
                </li>
              </ul>
            </div>
            <div className="notion-dialog__actions">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowDisconnectModal(false)}
                disabled={disconnecting}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleDisconnect}
                disabled={disconnecting}
                style={{ backgroundColor: "#ef4444", color: "#ffffff" }}
              >
                {disconnecting ? "Disconnecting..." : "Confirm Disconnect"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
