import { lazy, Suspense } from "react";
import { Navigate, Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import ProfileSetup from "./pages/ProfileSetup";
import Profile from "./pages/Profile";
import CareerTrack from "./pages/CareerTrack";
import CareerSkill from "./pages/CareerSkill";
import Analysis from "./pages/Analysis";
import AnalysisResults from "./pages/AnalysisResults";
import CapabilityMap from "./pages/CapabilityMap";
import Roadmap from "./pages/Roadmap";
import AIReviewTest from "./pages/AIReviewTest";
import Interview from "./pages/Interview";
import { ProtectedRoute, GuestOnly } from "./components/auth/ProtectedRoute";
import AppLayout from "./components/layout/AppLayout";

// The landing page carries the liquid metal hero (animation + 3D shader libraries), so it loads
// separately: students opening the app after login never download that code
const Landing = lazy(() => import("./pages/Landing"));
// Same for sign-up and login (animation, confetti and icon libraries)
const Signup = lazy(() => import("./pages/Signup"));
const Login = lazy(() => import("./pages/Login"));

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Suspense fallback={null}><Landing /></Suspense>} />
      {/* Dev health check */}
      <Route path="/health" element={<Home />} />

      {/* Auth — guest only (redirects to /dashboard if already logged in) */}
      <Route
        path="/login"
        element={
          <GuestOnly>
            <Suspense fallback={null}><Login /></Suspense>
          </GuestOnly>
        }
      />
      <Route
        path="/signup"
        element={
          <GuestOnly>
            <Suspense fallback={null}><Signup /></Suspense>
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
      {/* Logged-in pages share the top bar + sidebar */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        {/* Career Track is the home screen; the old dashboard address still works */}
        <Route path="/dashboard" element={<Navigate to="/career-track" replace />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/analysis/results" element={<AnalysisResults />} />
        <Route path="/analysis/capabilities" element={<CapabilityMap />} />
        <Route path="/roadmap" element={<Roadmap />} />
        {/* Career Track: one page per career and one per skill, rendered from the role's data */}
        <Route path="/career-track" element={<CareerTrack />} />
        <Route path="/career-track/:careerId" element={<CareerTrack />} />
        <Route path="/career-track/:careerId/:skillId" element={<CareerSkill />} />
        {/* Adaptive AI mock interview — evidence source (kept separate from AI Career Review) */}
        <Route path="/interview" element={<Interview />} />
        {/* EXPERIMENTAL side feature — isolated, no impact on other routes */}
        <Route path="/ai-review-test" element={<AIReviewTest />} />
      </Route>

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
