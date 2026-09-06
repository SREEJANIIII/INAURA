import { Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ProfileSetup from "./pages/ProfileSetup";
import Dashboard from "./pages/Dashboard";
import Analysis from "./pages/Analysis";
import AnalysisResults from "./pages/AnalysisResults";
import Roadmap from "./pages/Roadmap";
import { ProtectedRoute, GuestOnly } from "./components/auth/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      {/* Dev health check */}
      <Route path="/health" element={<Home />} />

      {/* Auth — guest only (redirects to /dashboard if already logged in) */}
      <Route
        path="/login"
        element={
          <GuestOnly>
            <Login />
          </GuestOnly>
        }
      />
      <Route
        path="/signup"
        element={
          <GuestOnly>
            <Signup />
          </GuestOnly>
        }
      />

      {/* Protected */}
      <Route
        path="/profile/setup"
        element={
          <ProtectedRoute>
            <ProfileSetup />
          </ProtectedRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analysis"
        element={
          <ProtectedRoute>
            <Analysis />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analysis/results"
        element={
          <ProtectedRoute>
            <AnalysisResults />
          </ProtectedRoute>
        }
      />
      <Route
        path="/roadmap"
        element={
          <ProtectedRoute>
            <Roadmap />
          </ProtectedRoute>
        }
      />

      <Route
        path="*"
        element={
          <div style={{ padding: "4rem 1.5rem", textAlign: "center" }}>
            <h2 style={{ fontSize: "1.4rem", fontWeight: 700 }}>404 — Not found</h2>
            <a href="/" style={{ color: "#4f46e5", fontWeight: 600 }}>
              Go home
            </a>
          </div>
        }
      />
    </Routes>
  );
}
