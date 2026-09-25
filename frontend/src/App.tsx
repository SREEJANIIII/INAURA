import { lazy, Suspense, type ReactNode } from "react";
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
import AtsTester from "./pages/AtsTester";
import Resume from "./pages/Resume";
import Revision from "./pages/Revision";
import { ProtectedRoute, GuestOnly } from "./components/auth/ProtectedRoute";
import AppLayout from "./components/layout/AppLayout";
import NotFound from "./pages/NotFound";

// Every page is its own download, so a student opening Career Track on a phone doesn't wait
// for the interview recorder, the ATS tester or the landing page's 3D hero.
const Landing = lazy(() => import("./pages/Landing"));
const Signup = lazy(() => import("./pages/Signup"));
const Login = lazy(() => import("./pages/Login"));
const ResetPassword = lazy(() => import("./pages/ResetPassword"));
const Home = lazy(() => import("./pages/Home"));
const ProfileSetup = lazy(() => import("./pages/ProfileSetup"));
const Profile = lazy(() => import("./pages/Profile"));
const CareerTrack = lazy(() => import("./pages/CareerTrack"));
const CareerSkill = lazy(() => import("./pages/CareerSkill"));
const Analysis = lazy(() => import("./pages/Analysis"));
const AnalysisResults = lazy(() => import("./pages/AnalysisResults"));
const CapabilityMap = lazy(() => import("./pages/CapabilityMap"));
const SkillAssessment = lazy(() => import("./pages/SkillAssessment"));
const Roadmap = lazy(() => import("./pages/Roadmap"));
const AIReviewTest = lazy(() => import("./pages/AIReviewTest"));
const Interview = lazy(() => import("./pages/Interview"));
const AtsTester = lazy(() => import("./pages/AtsTester"));
const Revision = lazy(() => import("./pages/Revision"));

/** Pages outside the app frame load without a placeholder: they're quick and full-screen */
const Bare = ({ children }: { children: ReactNode }) => <Suspense fallback={null}>{children}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Bare><Landing /></Bare>} />
      {/* Dev health check */}
      <Route path="/health" element={<Bare><Home /></Bare>} />

      {/* Auth — guest only (sends a signed-in visitor on to where they were going) */}
      <Route path="/login" element={<GuestOnly><Bare><Login /></Bare></GuestOnly>} />
      <Route path="/signup" element={<GuestOnly><Bare><Signup /></Bare></GuestOnly>} />
      {/* The password-reset email lands here, signed in by the link itself */}
      <Route path="/reset-password" element={<Bare><ResetPassword /></Bare>} />

      {/* Protected */}
      <Route
        path="/profile/setup"
        element={
          <ProtectedRoute>
            <Bare><ProfileSetup /></Bare>
          </ProtectedRoute>
        }
      />
      {/* Logged-in pages share the top bar + sidebar; AppLayout shows a placeholder while each loads */}
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
        <Route path="/skill-assessment" element={<SkillAssessment view="skills" />} />
        <Route path="/skill-assessment/dsa" element={<SkillAssessment view="dsa" />} />
        <Route path="/roadmap" element={<Roadmap />} />
        <Route path="/revision" element={<Revision />} />
        {/* Career Track: one page per career and one per skill, rendered from the role's data */}
        <Route path="/career-track" element={<CareerTrack />} />
        <Route path="/career-track/:careerId" element={<CareerTrack />} />
        <Route path="/career-track/:careerId/:skillId" element={<CareerSkill />} />
        {/* Adaptive AI mock interview — evidence source (kept separate from AI Career Review) */}
        <Route path="/interview" element={<Interview />} />
        {/* Resume section & ATS Tester */}
        <Route path="/resume" element={<Resume />} />
        <Route path="/resume/ats-tester" element={<AtsTester />} />
        {/* EXPERIMENTAL side feature — isolated, no impact on other routes */}
        <Route path="/ai-review-test" element={<AIReviewTest />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
