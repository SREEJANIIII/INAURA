import { useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE_URL } from "../services/api";
import { checkHealth, type HealthResponse } from "../services/health";

type HealthState =
  | { status: "idle"; data: null; error: null }
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: HealthResponse; error: null }
  | { status: "error"; data: null; error: string };

export default function Home() {
  const [health, setHealth] = useState<HealthState>({
    status: "idle",
    data: null,
    error: null,
  });

  const handleCheck = async () => {
    setHealth({ status: "loading", data: null, error: null });
    try {
      const data = await checkHealth();
      setHealth({ status: "success", data, error: null });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unknown error checking backend";
      setHealth({ status: "error", data: null, error: message });
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <div style={{ marginBottom: "1rem" }}>
        <Link
          to="/"
          style={{
            fontSize: "0.88rem",
            fontWeight: 600,
            color: "#4f46e5",
            textDecoration: "none",
          }}
        >
          ← Back to INAURA
        </Link>
      </div>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ margin: 0, fontSize: "2.25rem", fontWeight: 700 }}>
          INAURA
        </h1>
        <p style={{ margin: "0.35rem 0 0", color: "#666", fontSize: "1.05rem" }}>
          Bridging skills to industry.
        </p>
        <p style={{ margin: "0.75rem 0 0", color: "#444", lineHeight: 1.5 }}>
          Minimal app shell — Phase 1 verifies{" "}
          <code>frontend → FastAPI</code> connectivity via{" "}
          <code>/api/v1/health</code>.
        </p>
      </header>

      <section
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: "1.25rem",
          background: "#fff",
        }}
      >
        <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.15rem" }}>
          Backend Connection Check
        </h2>
        <p style={{ margin: "0 0 1rem", color: "#666", fontSize: "0.9rem" }}>
          API base: <code>{API_BASE_URL}</code>
        </p>

        <button
          type="button"
          onClick={handleCheck}
          disabled={health.status === "loading"}
          style={{
            padding: "0.6rem 1rem",
            borderRadius: 8,
            border: "1px solid #111",
            background: health.status === "loading" ? "#eee" : "#111",
            color: health.status === "loading" ? "#666" : "#fff",
            cursor: health.status === "loading" ? "not-allowed" : "pointer",
            fontWeight: 600,
          }}
        >
          {health.status === "loading"
            ? "Checking…"
            : "Check Backend Connection"}
        </button>

        <div style={{ marginTop: "1rem", minHeight: 60 }}>
          {health.status === "idle" && (
            <p style={{ color: "#888", fontSize: "0.9rem", margin: 0 }}>
              Click the button to call <code>GET /api/v1/health</code>.
            </p>
          )}
          {health.status === "loading" && (
            <p style={{ color: "#666", margin: 0 }}>Contacting FastAPI…</p>
          )}
          {health.status === "success" && health.data && (
            <div
              style={{
                background: "#f0fdf4",
                border: "1px solid #bbf7d0",
                borderRadius: 8,
                padding: "0.75rem 1rem",
              }}
            >
              <div style={{ color: "#15803d", fontWeight: 600 }}>
                ● Connected — {health.data.status}
              </div>
              <div style={{ fontSize: "0.9rem", marginTop: 4 }}>
                <div>
                  <strong>Service:</strong> {health.data.service}
                </div>
                <div>
                  <strong>Message:</strong> {health.data.message}
                </div>
              </div>
              <pre
                style={{
                  margin: "0.5rem 0 0",
                  fontSize: "0.8rem",
                  background: "#fff",
                  padding: "0.5rem",
                  borderRadius: 6,
                  overflowX: "auto",
                }}
              >
                {JSON.stringify(health.data, null, 2)}
              </pre>
            </div>
          )}
          {health.status === "error" && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 8,
                padding: "0.75rem 1rem",
              }}
            >
              <div style={{ color: "#dc2626", fontWeight: 600 }}>
                ● Not connected
              </div>
              <div
                style={{
                  fontSize: "0.9rem",
                  marginTop: 4,
                  wordBreak: "break-word",
                }}
              >
                {health.error}
              </div>
              <p
                style={{
                  fontSize: "0.85rem",
                  color: "#666",
                  margin: "0.5rem 0 0",
                }}
              >
                Ensure backend is running:{" "}
                <code>uvicorn app.main:app --reload --port 8000</code>
              </p>
            </div>
          )}
        </div>
      </section>

      <footer
        style={{
          marginTop: "2rem",
          paddingTop: "1rem",
          borderTop: "1px solid #eee",
          color: "#888",
          fontSize: "0.85rem",
        }}
      >
        <div>
          Phase 1 — Minimal shell. No RAG, scoring, auth, or DB yet.
        </div>
        <div style={{ marginTop: 4 }}>
          Vite dev proxy: <code>/api → http://localhost:8000</code> • CORS
          enabled for <code>http://localhost:5173</code>
        </div>
      </footer>
    </div>
  );
}
