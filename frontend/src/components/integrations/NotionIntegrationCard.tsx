import { useEffect, useState, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Button from "../ui/app-button";
import {
  getNotionStatus,
  getNotionConnectUrl,
  syncNotion,
  disconnectNotion,
  type NotionStatus,
  type NotionSyncResult,
  type NotionSyncedPage,
  type NotionEvidenceItem,
} from "../../services/notion";
import { refreshPageData } from "../../lib/pageData";
import "./NotionIntegrationCard.css";

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
  const [banner, setBanner] = useState<{ type: "success" | "error" | "info"; message: string } | null>(null);
  const [showPrivacy, setShowPrivacy] = useState(false);

  // View & filtering states
  const [activeTab, setActiveTab] = useState<"pages" | "signals">("pages");
  const [searchQuery, setSearchQuery] = useState("");
  const [skillFilter, setSkillFilter] = useState("all");
  const [depthFilter, setDepthFilter] = useState("all");
  const [expandedPageIds, setExpandedPageIds] = useState<Set<string>>(new Set());

  const location = useLocation();
  const navigate = useNavigate();

  const loadStatus = async () => {
    try {
      setLoading(true);
      const data = await getNotionStatus();
      setStatus(data);
    } catch (err) {
      console.error("Failed to load Notion status:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();

    // Check URL parameters for OAuth redirect callbacks
    const params = new URLSearchParams(location.search);
    const notionParam = params.get("notion");
    const errorParam = params.get("notion_error");

    if (notionParam === "connected") {
      setBanner({
        type: "success",
        message: "Notion connected successfully! INAURA can now analyze your authorized notes.",
      });
      params.delete("notion");
      navigate({ search: params.toString(), hash: location.hash }, { replace: true });
    } else if (errorParam) {
      const errorMessages: Record<string, string> = {
        access_denied: "Notion authorization was denied. You can connect anytime when ready.",
        invalid_state: "Security verification failed (expired or invalid state). Please try again.",
        missing_code_or_state: "Missing OAuth response data from Notion. Please try again.",
        token_exchange_failed: "Could not exchange code with Notion OAuth service. Please retry.",
      };
      setBanner({
        type: "error",
        message: errorMessages[errorParam] || `Notion connection failed: ${errorParam}`,
      });
      params.delete("notion_error");
      navigate({ search: params.toString(), hash: location.hash }, { replace: true });
    }
  }, [location.search]);

  const handleConnect = async () => {
    try {
      setConnecting(true);
      setBanner(null);
      const authUrl = await getNotionConnectUrl();
      window.location.href = authUrl;
    } catch (err: any) {
      setConnecting(false);
      setBanner({
        type: "error",
        message: err?.message || "Failed to start Notion authorization. Please try again.",
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
    } catch (err: any) {
      setSyncingStep(null);
      setBanner({
        type: "error",
        message: err?.message || "Synchronization failed. Please check your connection and try again.",
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
    } catch (err: any) {
      setBanner({
        type: "error",
        message: err?.message || "Failed to disconnect Notion. Please try again.",
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

  // Synced pages and aggregated evidence items
  const syncedPages: NotionSyncedPage[] = useMemo(() => {
    return status?.synced_pages || syncResult?.synced_pages || [];
  }, [status, syncResult]);

  const allSkills = useMemo(() => {
    const s = new Set<string>();
    syncedPages.forEach((p) => {
      (p.skills || []).forEach((sk) => s.add(sk));
    });
    return Array.from(s).sort();
  }, [syncedPages]);

  const allEvidenceItems = useMemo(() => {
    const items: NotionEvidenceItem[] = [];
    syncedPages.forEach((p) => {
      (p.extracted_evidence || []).forEach((e) => {
        items.push({
          ...e,
          sourcePageTitle: e.sourcePageTitle || p.page_title,
          sourceUrl: e.sourceUrl || p.page_url,
        });
      });
    });
    return items;
  }, [syncedPages]);

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
          <span className="notion-card__badge" style={{ background: "rgba(0,0,0,0.06)", color: "#64748b" }}>
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
              style={{ color: "#ef4444" }}
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

                      return (
                        <div key={page.page_id} className="notion-page-card">
                          <div className="notion-page-card__head">
                            <div className="notion-page-card__info">
                              <span className="notion-page-card__icon" aria-hidden="true">
                                📄
                              </span>
                              <div>
                                <h4 className="notion-page-card__title">
                                  <span>{page.page_title}</span>
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
