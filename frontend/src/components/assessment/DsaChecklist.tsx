import { useCallback, useEffect, useMemo, useState } from "react";
import {
  toggleDsaQuestion,
  syncDsaLeetCode,
  importDsaSolvedText,
  type DsaQuestion,
  type DsaChecklistMetrics,
} from "../../services/assessment";
import { dsaChecklistData } from "../../lib/pageData";
import "./DsaChecklist.css";
import { friendlyError } from "../../lib/errors";

const LOCAL_STORAGE_KEY = "inaura_dsa_solved_ids";

function getCachedSolved(): Set<string> {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function setCachedSolved(ids: Set<string>) {
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Ignore storage quota errors
  }
}

type Props = {
  onProgressUpdate?: () => void;
};

export default function DsaChecklist({ onProgressUpdate }: Props) {
  const [questions, setQuestions] = useState<DsaQuestion[]>([]);
  const [solvedIds, setSolvedIds] = useState<Set<string>>(() => getCachedSolved());
  const [metrics, setMetrics] = useState<DsaChecklistMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<string>("all");
  const [selectedDifficulty, setSelectedDifficulty] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [syncTab, setSyncTab] = useState<"api" | "import">("api");
  const [syncUsername, setSyncUsername] = useState("");
  const [importText, setImportText] = useState("");
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncModalMessage, setSyncModalMessage] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    const timer = setTimeout(() => setToastMessage(null), 3500);
    return () => clearTimeout(timer);
  }, []);

  // Fetch from backend
  useEffect(() => {
    let active = true;
    // The shared copy, so opening this page twice doesn't re-ask the server
    dsaChecklistData
      .fetch()
      .then((res) => {
        if (!active) return;
        setQuestions(res.questions);
        const serverSolved = new Set(res.solved_ids || []);
        // Merge with local cache so newly checked items never get wiped
        const merged = new Set([...Array.from(getCachedSolved()), ...Array.from(serverSolved)]);
        setSolvedIds(merged);
        setCachedSolved(merged);
        setMetrics(res.metrics);
        setError(null);
      })
      .catch((e) => {
        if (active) setError(friendlyError(e, "Failed to load DSA checklist"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Handle single question toggle
  const handleToggle = async (question: DsaQuestion) => {
    const isCurrentlySolved = solvedIds.has(question.id);
    const nextState = !isCurrentlySolved;

    // 1. Optimistic UI update
    setSolvedIds((prev) => {
      const next = new Set(prev);
      if (nextState) next.add(question.id);
      else next.delete(question.id);
      setCachedSolved(next);
      return next;
    });

    showToast(
      nextState
        ? `Marked "${question.title}" as solved. DSA gap updated!`
        : `Unmarked "${question.title}".`
    );

    // 2. Call backend
    try {
      const res = await toggleDsaQuestion(question.id, nextState);
      if (res.metrics) setMetrics(res.metrics);
      if (res.solved_ids) {
        const updatedSet = new Set(res.solved_ids);
        setSolvedIds(updatedSet);
        setCachedSolved(updatedSet);
      }
      onProgressUpdate?.();
    } catch (err) {
      // Best-effort; offline cached state is preserved
      console.warn("Could not sync DSA question state to server:", err);
    }
  };

  const handleSyncLeetCode = async () => {
    setSyncLoading(true);
    setSyncModalMessage(null);
    try {
      const res = await syncDsaLeetCode(syncUsername);
      if (res.success) {
        if (res.metrics) setMetrics(res.metrics);
        const updated = await dsaChecklistData.fetch(true);
        const nextSet = new Set(updated.solved_ids || []);
        setSolvedIds(nextSet);
        setCachedSolved(nextSet);
        if (updated.metrics) setMetrics(updated.metrics);

        setSyncModalMessage({
          type: "success",
          text: res.message,
        });
        showToast(
          res.synced_count > 0
            ? `Synced ${res.synced_count} question${res.synced_count !== 1 ? "s" : ""} from LeetCode!`
            : "LeetCode profile synced."
        );
        onProgressUpdate?.();
      } else {
        setSyncModalMessage({
          type: "error",
          text: res.message,
        });
      }
    } catch (e) {
      setSyncModalMessage({
        type: "error",
        text: friendlyError(e, "Failed to sync with LeetCode. Please check your username."),
      });
    } finally {
      setSyncLoading(false);
    }
  };

  const handleBulkImport = async () => {
    if (!importText.trim()) return;
    setSyncLoading(true);
    setSyncModalMessage(null);
    try {
      const res = await importDsaSolvedText(importText);
      if (res.success) {
        if (res.metrics) setMetrics(res.metrics);
        const updated = await dsaChecklistData.fetch(true);
        const nextSet = new Set(updated.solved_ids || []);
        setSolvedIds(nextSet);
        setCachedSolved(nextSet);
        if (updated.metrics) setMetrics(updated.metrics);

        setSyncModalMessage({
          type: "success",
          text: res.message,
        });
        showToast(`Imported ${res.imported_count} question${res.imported_count !== 1 ? "s" : ""}!`);
        setImportText("");
        onProgressUpdate?.();
      } else {
        setSyncModalMessage({
          type: "error",
          text: res.message,
        });
      }
    } catch (e) {
      setSyncModalMessage({
        type: "error",
        text: friendlyError(e, "Failed to import questions. Please check the text."),
      });
    } finally {
      setSyncLoading(false);
    }
  };

  // Distinct topics list
  const topics = useMemo(() => {
    const set = new Set<string>();
    questions.forEach((q) => set.add(q.topic));
    return Array.from(set);
  }, [questions]);

  // Filtered questions
  const filteredQuestions = useMemo(() => {
    return questions.filter((q) => {
      // Topic filter
      if (selectedTopic !== "all" && q.topic !== selectedTopic) return false;
      // Difficulty filter
      if (selectedDifficulty !== "all" && q.difficulty !== selectedDifficulty) return false;
      // Status filter
      const isSolved = solvedIds.has(q.id);
      if (selectedStatus === "solved" && !isSolved) return false;
      if (selectedStatus === "unsolved" && isSolved) return false;
      // Search filter
      if (searchQuery.trim()) {
        const qText = searchQuery.toLowerCase();
        const matchesTitle = q.title.toLowerCase().includes(qText);
        const matchesPattern = q.pattern.toLowerCase().includes(qText);
        const matchesTopic = q.topic.toLowerCase().includes(qText);
        if (!matchesTitle && !matchesPattern && !matchesTopic) return false;
      }
      return true;
    });
  }, [questions, selectedTopic, selectedDifficulty, selectedStatus, searchQuery, solvedIds]);

  // Group filtered questions by topic
  const groupedByTopic = useMemo(() => {
    const map = new Map<string, DsaQuestion[]>();
    for (const q of filteredQuestions) {
      if (!map.has(q.topic)) map.set(q.topic, []);
      map.get(q.topic)!.push(q);
    }
    return map;
  }, [filteredQuestions]);

  const totalQuestions = questions.length || 71;
  const solvedCount = solvedIds.size;
  const pct = Math.min(100, Math.round((solvedCount / totalQuestions) * 100));
  const isGapCovered = pct >= 50 || (metrics?.score ?? 0) >= 0.5;

  return (
    <div className="dsa-hub" id="dsa-checklist">
      {/* Hero card */}
      <section className="dsa-hero" aria-labelledby="dsa-hero-title">
        <div className="dsa-hero__badge">
          <span>INAURA × NeetCode</span>
          <span>·</span>
          <span>Compulsory Patterns</span>
        </div>

        <div className="dsa-hero__head">
          <div>
            <h2 id="dsa-hero-title">Industry DSA Mastery & Pattern Checklist</h2>
            <p className="dsa-hero__desc">
              Master the 15 core algorithmic patterns tested in software engineering interviews.
              Tick off questions you have solved on NeetCode or LeetCode — every completed question
              directly raises your verified algorithmic score and covers your DSA skill gap.
            </p>
          </div>

          <div className="dsa-hero__actions">
            <button
              type="button"
              className="dsa-sync-btn"
              onClick={() => {
                setShowSyncModal(true);
                setSyncModalMessage(null);
              }}
              title="Sync or import problems you've already solved on LeetCode"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
              </svg>
              <span>Sync LeetCode Solved</span>
            </button>

            <div
              className={`dsa-hero__impact-badge ${
                isGapCovered
                  ? "dsa-hero__impact-badge--covered"
                  : "dsa-hero__impact-badge--progress"
              }`}
            >
              {isGapCovered ? "✓ DSA Skill Gap Covered" : `DSA Gap: ${100 - pct}% remaining`}
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div className="dsa-progress-block">
          <div className="dsa-progress-header">
            <span>
              <strong>{solvedCount}</strong> of <strong>{totalQuestions}</strong> questions completed
            </span>
            <span className="dsa-progress-pct">{pct}%</span>
          </div>
          <div className="dsa-meter-bar" aria-hidden="true">
            <div className="dsa-meter-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>

        {/* Difficulty stats row */}
        <div className="dsa-stats-row">
          <div className="dsa-stat-chip">
            <span className="dsa-chip-dot dsa-chip-dot--easy" />
            <span>
              Easy:{" "}
              <strong>
                {questions.filter((q) => q.difficulty === "Easy" && solvedIds.has(q.id)).length} /{" "}
                {questions.filter((q) => q.difficulty === "Easy").length}
              </strong>
            </span>
          </div>
          <div className="dsa-stat-chip">
            <span className="dsa-chip-dot dsa-chip-dot--medium" />
            <span>
              Medium:{" "}
              <strong>
                {questions.filter((q) => q.difficulty === "Medium" && solvedIds.has(q.id)).length} /{" "}
                {questions.filter((q) => q.difficulty === "Medium").length}
              </strong>
            </span>
          </div>
          <div className="dsa-stat-chip">
            <span className="dsa-chip-dot dsa-chip-dot--hard" />
            <span>
              Hard:{" "}
              <strong>
                {questions.filter((q) => q.difficulty === "Hard" && solvedIds.has(q.id)).length} /{" "}
                {questions.filter((q) => q.difficulty === "Hard").length}
              </strong>
            </span>
          </div>
          <div className="dsa-stat-chip" style={{ marginLeft: "auto" }}>
            <span>
              Pattern Breadth:{" "}
              <strong>
                {topics.filter((t) =>
                  questions.some((q) => q.topic === t && solvedIds.has(q.id))
                ).length}{" "}
                / {topics.length} topics
              </strong>
            </span>
          </div>
        </div>
      </section>

      {/* Interactive Controls & Filters */}
      <div className="dsa-controls">
        {/* Search */}
        <div className="dsa-search-bar">
          <svg
            className="dsa-search-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
          >
            <circle cx="7" cy="7" r="5" />
            <path d="m11 11 3.5 3.5" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            className="dsa-search-input"
            placeholder="Filter by question, pattern (e.g. two pointers, monotonic stack, bfs)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Filter DSA questions"
          />
        </div>

        {/* Topic Pills Rail */}
        <div className="dsa-topic-pills" role="tablist" aria-label="DSA Topics">
          <button
            type="button"
            className={`dsa-pill ${selectedTopic === "all" ? "is-active" : ""}`}
            onClick={() => setSelectedTopic("all")}
          >
            <span>All Patterns</span>
            <span className="dsa-pill-count">{questions.length}</span>
          </button>
          {topics.map((topic) => {
            const topicTotal = questions.filter((q) => q.topic === topic).length;
            const topicSolved = questions.filter((q) => q.topic === topic && solvedIds.has(q.id)).length;
            return (
              <button
                key={topic}
                type="button"
                className={`dsa-pill ${selectedTopic === topic ? "is-active" : ""}`}
                onClick={() => setSelectedTopic(topic)}
              >
                <span>{topic}</span>
                <span className="dsa-pill-count">
                  {topicSolved}/{topicTotal}
                </span>
              </button>
            );
          })}
        </div>

        {/* Subfilter select row */}
        <div className="dsa-filter-subrow">
          <div className="dsa-subfilters">
            <select
              className="dsa-select"
              value={selectedDifficulty}
              onChange={(e) => setSelectedDifficulty(e.target.value)}
              aria-label="Filter by difficulty"
            >
              <option value="all">All Difficulties</option>
              <option value="Easy">Easy</option>
              <option value="Medium">Medium</option>
              <option value="Hard">Hard</option>
            </select>

            <select
              className="dsa-select"
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              aria-label="Filter by status"
            >
              <option value="all">All Statuses</option>
              <option value="unsolved">Incomplete only</option>
              <option value="solved">Solved only</option>
            </select>
          </div>

          <span style={{ fontSize: "12.5px", color: "var(--muted-2)" }}>
            Showing {filteredQuestions.length} of {totalQuestions} questions
          </span>
        </div>
      </div>

      {/* Error state */}
      {error && <div className="rm-alert rm-alert--error">{error}</div>}

      {/* Questions list grouped by topic */}
      {loading && questions.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", color: "var(--muted-2)" }}>
          Loading compulsory pattern question bank…
        </div>
      ) : filteredQuestions.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", color: "var(--muted-2)" }}>
          No questions match your filter. Try adjusting your search query or topic filter.
        </div>
      ) : (
        <div className="dsa-topics-list">
          {Array.from(groupedByTopic.entries()).map(([topic, topicQuestions]) => {
            const tSolved = topicQuestions.filter((q) => solvedIds.has(q.id)).length;
            const tPct = Math.round((tSolved / topicQuestions.length) * 100);

            return (
              <section key={topic} className="dsa-topic-card" aria-label={topic}>
                <header className="dsa-topic-head">
                  <h3 className="dsa-topic-title">{topic}</h3>
                  <div className="dsa-topic-meta">
                    <span>
                      {tSolved} of {topicQuestions.length} solved ({tPct}%)
                    </span>
                  </div>
                </header>

                <div className="dsa-questions">
                  {topicQuestions.map((q) => {
                    const isSolved = solvedIds.has(q.id);
                    return (
                      <div
                        key={q.id}
                        className={`dsa-q-row ${isSolved ? "is-solved" : ""}`}
                      >
                        {/* Checkbox */}
                        <label className="dsa-check-label" title={isSolved ? "Mark as unsolved" : "Mark as solved"}>
                          <input
                            type="checkbox"
                            className="dsa-check-input"
                            checked={isSolved}
                            onChange={() => handleToggle(q)}
                            aria-label={`Mark ${q.title} as solved`}
                          />
                        </label>

                        {/* Question details */}
                        <div className="dsa-q-info">
                          <div className="dsa-q-top">
                            <span className="dsa-q-title">{q.title}</span>
                            <span
                              className={`dsa-diff-badge dsa-diff-badge--${q.difficulty.toLowerCase()}`}
                            >
                              {q.difficulty}
                            </span>
                            <span className="dsa-pattern-badge">{q.pattern}</span>
                          </div>
                          <div className="dsa-q-why">{q.why_it_matters}</div>
                        </div>

                        {/* Direct Practice Links */}
                        <div className="dsa-q-links">
                          <a
                            href={q.neetcode_url}
                            target="_blank"
                            rel="noreferrer"
                            className="dsa-link-btn dsa-link-btn--neetcode"
                            title={`Solve ${q.title} on NeetCode`}
                          >
                            NeetCode ↗
                          </a>
                          <a
                            href={q.leetcode_url}
                            target="_blank"
                            rel="noreferrer"
                            className="dsa-link-btn dsa-link-btn--leetcode"
                            title={`Solve ${q.title} on LeetCode`}
                          >
                            LeetCode ↗
                          </a>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Floating Save Toast */}
      {toastMessage && <div className="dsa-toast" role="status">{toastMessage}</div>}

      {/* Sync from LeetCode / Bulk Import Modal */}
      {showSyncModal && (
        <div
          className="dsa-modal-backdrop"
          onClick={() => !syncLoading && setShowSyncModal(false)}
          role="presentation"
        >
          <div
            className="dsa-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="sync-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dsa-modal-head">
              <div>
                <h3 id="sync-modal-title" className="dsa-modal-title">
                  Sync LeetCode Solved Questions
                </h3>
                <p className="dsa-modal-desc">
                  Fetch questions you have already solved on LeetCode to automatically check off patterns and cover your DSA skill gap.
                </p>
              </div>
              <button
                type="button"
                className="dsa-modal-close"
                onClick={() => !syncLoading && setShowSyncModal(false)}
                aria-label="Close dialog"
                disabled={syncLoading}
              >
                ✕
              </button>
            </div>

            <div className="dsa-modal-tabs">
              <button
                type="button"
                className={`dsa-modal-tab ${syncTab === "api" ? "is-active" : ""}`}
                onClick={() => {
                  setSyncTab("api");
                  setSyncModalMessage(null);
                }}
              >
                <span>⚡ Live LeetCode Sync</span>
              </button>
              <button
                type="button"
                className={`dsa-modal-tab ${syncTab === "import" ? "is-active" : ""}`}
                onClick={() => {
                  setSyncTab("import");
                  setSyncModalMessage(null);
                }}
              >
                <span>📋 Quick Paste / Import</span>
              </button>
            </div>

            <div className="dsa-modal-body">
              {syncTab === "api" ? (
                <div className="dsa-sync-pane">
                  <label className="dsa-field-label" htmlFor="lc-username-input">
                    LeetCode Username / Handle:
                  </label>
                  <div className="dsa-input-row">
                    <input
                      id="lc-username-input"
                      type="text"
                      className="dsa-input-text"
                      placeholder="e.g. your_leetcode_username (or leave blank to use connected profile)"
                      value={syncUsername}
                      onChange={(e) => setSyncUsername(e.target.value)}
                      disabled={syncLoading}
                    />
                    <button
                      type="button"
                      className="dsa-btn-primary"
                      onClick={handleSyncLeetCode}
                      disabled={syncLoading}
                    >
                      {syncLoading ? "Scanning LeetCode…" : "Fetch Solved"}
                    </button>
                  </div>
                  <p className="dsa-sync-help">
                    <strong>How it works:</strong> We query LeetCode’s public API for your recent accepted submissions. Any problems matching the 71 compulsory interview patterns are immediately checked off, updating your DSA skill gap and roadmap.
                  </p>
                </div>
              ) : (
                <div className="dsa-sync-pane">
                  <label className="dsa-field-label" htmlFor="lc-import-text">
                    Paste problem URLs, slugs, or titles:
                  </label>
                  <textarea
                    id="lc-import-text"
                    className="dsa-textarea"
                    rows={4}
                    placeholder="Paste problem links or names, e.g.:&#10;https://leetcode.com/problems/two-sum/&#10;3sum, Trapping Rain Water, coin-change, course-schedule..."
                    value={importText}
                    onChange={(e) => setImportText(e.target.value)}
                    disabled={syncLoading}
                  />
                  <div className="dsa-import-footer">
                    <span className="dsa-import-hint">
                      Accepts URLs, slugs, or comma/newline separated titles
                    </span>
                    <button
                      type="button"
                      className="dsa-btn-primary"
                      onClick={handleBulkImport}
                      disabled={syncLoading || !importText.trim()}
                    >
                      {syncLoading ? "Importing…" : "Import & Check Off"}
                    </button>
                  </div>
                  <p className="dsa-sync-help">
                    <strong>Tip:</strong> If you solved questions months ago that aren’t in your recent submissions, simply paste their names or links here to check them all off at once.
                  </p>
                </div>
              )}

              {syncModalMessage && (
                <div className={`dsa-sync-alert dsa-sync-alert--${syncModalMessage.type}`}>
                  {syncModalMessage.text}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
