import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Button from "../components/ui/Button";
import InterviewModal from "../components/assessment/InterviewModal";
import {
  answerMockQuestion,
  completeMockInterview,
  startMockInterview,
  type AnswerResponse,
  type InterviewReport,
  type MockQuestion,
  type StartInterviewResponse,
} from "../services/interview";
import "./Interview.css";

type Stage =
  | "setup"
  | "permissions"
  | "intro"
  | "question"
  | "evaluating"
  | "feedback"
  | "completing"
  | "report";

type CamState = "idle" | "requesting" | "live" | "denied" | "unavailable";

function pct(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${Math.round(v * 100)}%` : "—";
}

export default function Interview() {
  const [stage, setStage] = useState<Stage>("setup");
  const [targetRole, setTargetRole] = useState("");
  // Fixed 3-question adaptive interview: Q1 opening -> Q2 counter-question -> Q3 deep-dive.
  const questionCount = 3;
  const [answeredCount, setAnsweredCount] = useState(0);
  const [session, setSession] = useState<StartInterviewResponse | null>(null);
  const [current, setCurrent] = useState<MockQuestion | null>(null);
  const [answer, setAnswer] = useState("");
  const [lastResult, setLastResult] = useState<AnswerResponse | null>(null);
  const [report, setReport] = useState<InterviewReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [liveInterviewSkill, setLiveInterviewSkill] = useState<string | null>(null);

  // Camera / mic
  const [camState, setCamState] = useState<CamState>("idle");
  const [micState, setMicState] = useState<"idle" | "live" | "muted" | "error">("idle");
  const [micLevel, setMicLevel] = useState(0);
  const [audioFallback, setAudioFallback] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  // Dictation (browser SpeechRecognition with fallback)
  const [dictating, setDictating] = useState(false);
  const recogRef = useRef<{ stop: () => void; start: () => void } | null>(null);
  const speechSupported =
    typeof window !== "undefined" &&
    Boolean(
      (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown })
        .SpeechRecognition ||
        (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown })
          .webkitSpeechRecognition
    );

  // Timer
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<number | null>(null);

  const stopTracks = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    try {
      audioCtxRef.current?.close();
    } catch {
      /* ignore */
    }
    audioCtxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    });
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  useEffect(() => stopTracks, [stopTracks]);

  useEffect(() => {
    if (stage === "question") {
      const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
      timerRef.current = id;
      return () => {
        window.clearInterval(id);
      };
    }
    if (timerRef.current) window.clearInterval(timerRef.current);
    return undefined;
  }, [stage, current?.id]);

  const requestMedia = useCallback(async () => {
    setCamState("requesting");
    setMicState("idle");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCamState("unavailable");
        setMicState("error");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCamState("live");
      setMicState("live");
      // Mic level meter (presence only — no recording by default)
      try {
        const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx: AudioContext = new Ctx();
        audioCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteTimeDomainData(buf);
          let peak = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = Math.abs(buf[i] - 128) / 128;
            if (v > peak) peak = v;
          }
          setMicLevel(Math.min(1, peak * 1.6));
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        /* meter optional */
      }
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError") {
        setCamState("denied");
        setMicState("muted");
      } else {
        setCamState("unavailable");
        setMicState("error");
      }
    }
  }, []);

  const handleStart = async () => {
    setBusy(true);
    setError(null);
    setAnsweredCount(0);
    try {
      const res = await startMockInterview(targetRole.trim() || undefined, questionCount);
      setSession(res);
      setCurrent(res.current_question);
      setStage("permissions");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the interview");
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = async () => {
    if (!session || !current || !answer.trim()) return;
    setStage("evaluating");
    setError(null);
    try {
      const res = await answerMockQuestion(session.session_id, answer.trim(), current.id);
      setLastResult(res);
      setAnswer("");
      // Progress counts SUCCESSFULLY SUBMITTED answers only — never the
      // number of generated/displayed questions. Server is authoritative.
      setAnsweredCount(typeof res.answered_count === "number" ? res.answered_count : (n) => n + 1);
      if (res.next_action === "complete" || !res.current_question) {
        setStage("feedback");
      } else {
        setCurrent(res.current_question);
        setStage("feedback");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit your answer");
      setStage("question");
    }
  };

  const handleNext = () => {
    if (!lastResult) return;
    if (lastResult.next_action === "complete" || !lastResult.current_question) {
      void handleComplete();
      return;
    }
    setCurrent(lastResult.current_question);
    setLastResult(null);
    setStage("question");
  };

  const handleComplete = async () => {
    if (!session) return;
    setStage("completing");
    setError(null);
    try {
      const rep = await completeMockInterview(session.session_id);
      setReport(rep);
      setStage("report");
      stopTracks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not complete the interview");
      setStage("feedback");
    }
  };

  const toggleDictation = () => {
    if (!speechSupported) {
      setAudioFallback(true);
      return;
    }
    const win = window as unknown as {
      SpeechRecognition?: new () => {
        lang: string;
        interimResults: boolean;
        continuous: boolean;
        onresult: ((ev: { resultIndex: number; results: Array<Array<{ transcript: string }>> }) => void) | null;
        onend: (() => void) | null;
        onerror: (() => void) | null;
        start: () => void;
        stop: () => void;
      };
      webkitSpeechRecognition?: new () => {
        lang: string;
        interimResults: boolean;
        continuous: boolean;
        onresult: ((ev: { resultIndex: number; results: Array<Array<{ transcript: string }>> }) => void) | null;
        onend: (() => void) | null;
        onerror: (() => void) | null;
        start: () => void;
        stop: () => void;
      };
    };
    const Impl = win.SpeechRecognition || win.webkitSpeechRecognition;
    if (dictating) {
      try {
        recogRef.current?.stop();
      } catch {
        /* ignore */
      }
      setDictating(false);
      return;
    }
    try {
      if (!Impl) return;
      const recog = new Impl();
      recogRef.current = recog;
      recog.lang = "en-US";
      recog.interimResults = true;
      recog.continuous = false;
      recog.onresult = (ev: { resultIndex: number; results: Array<Array<{ transcript: string }>> }) => {
        let text = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          text += ev.results[i][0].transcript;
        }
        setAnswer((prev) => (prev ? `${prev} ${text}` : text));
      };
      recog.onend = () => setDictating(false);
      recog.onerror = () => {
        setDictating(false);
        setAudioFallback(true);
      };
      recog.start();
      setDictating(true);
    } catch {
      setAudioFallback(true);
    }
  };

  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  // Progress is answered_questions / 3 — never questions.length. answeredCount
  // only advances after a successful submit, so display stays 0/3 until Q1 lands.
  const totalQuestions = 3;
  const progress = Math.min(100, (answeredCount / totalQuestions) * 100);

  return (
    <div className="iv">
      <header className="iv__header">
        <div className="container iv__header-inner">
          <Link to="/dashboard" className="iv__brand">← Dashboard</Link>
          <span className="iv__badge">AI Mock Interview · Evidence source</span>
        </div>
      </header>

      <main className="container iv__main">
        {error && (
          <div className="iv__error" role="alert">
            {error}
          </div>
        )}

        {stage === "setup" && (
          <section className="iv__card">
            <div className="iv__eyebrow">Pre-interview setup</div>
            <h1 className="iv__title">Personalized mock interview</h1>
            <p className="iv__sub">
              Questions are generated from your actual evidence — GitHub projects, coding profiles,
              assessments, and gaps against your target role — not a fixed script. Your answers become{" "}
              <strong>additional skill evidence</strong> that corroborates or challenges what INAURA already knows.
            </p>
            <label className="iv__label">
              Target role
              <input
                className="iv__input"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="e.g. Backend Developer (defaults to your analysis role)"
              />
            </label>
            <div className="iv__label">
              3 adaptive questions — an opening, a counter-question on your answer, then a deep-dive.
            </div>
            <div className="iv__row">
              <Button variant="primary" size="lg" onClick={handleStart} disabled={busy}>
                {busy ? "Preparing your interview…" : "Prepare my interview"}
              </Button>
            </div>

            <div style={{ marginTop: 28, padding: "20px", background: "rgba(79, 70, 229, 0.08)", borderRadius: 12, border: "1px solid rgba(79, 70, 229, 0.2)" }}>
              <div style={{ fontWeight: 700, color: "#4f46e5", fontSize: "1.05rem", marginBottom: 6 }}>
                🎙 Live Video AI Interview (Zoom / Google Meet Style)
              </div>
              <p style={{ fontSize: "0.88rem", color: "#475569", margin: "0 0 14px 0", lineHeight: 1.5 }}>
                Have a natural verbal video interview with the INAURA AI interviewer. The AI interviewer speaks directly to you, listens via speech recognition, and adapts dynamically.
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#334155" }}>Start with Skill:</span>
                {["Python", "DSA", "SQL", "React", "Java", "JavaScript"].map((s) => (
                  <Button
                    key={s}
                    variant="secondary"
                    size="sm"
                    onClick={() => setLiveInterviewSkill(s)}
                  >
                    {s}
                  </Button>
                ))}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setLiveInterviewSkill("Python")}
                  style={{ marginLeft: "auto" }}
                >
                  Let&apos;s Begin Live Call
                </Button>
              </div>
            </div>

            <p className="iv__fine">
              Camera stays on this device for presence. No video is uploaded or stored. Gemini grading
              happens server-side — your API keys never reach the browser.
            </p>
          </section>
        )}

        {stage === "permissions" && session && (
          <section className="iv__grid">
            <div className="iv__card">
              <div className="iv__eyebrow">Camera & microphone</div>
              <h2 className="iv__h2">Check your presence</h2>
              <div className="iv__video-wrap">
                <video ref={videoRef} className="iv__video" muted playsInline autoPlay />
                {camState !== "live" && <div className="iv__video-off">Camera preview off</div>}
                <span className={`iv__rec ${camState === "live" ? "iv__rec--live" : ""}`}>
                  {camState === "live" ? "● Preview (not recorded)" : "○ No preview"}
                </span>
              </div>
              <div className="iv__meter-row">
                <span className="iv__meter-label">
                  Mic: {micState === "live" ? "live" : micState === "muted" ? "blocked" : micState}
                </span>
                <div className="iv__meter">
                  <div className="iv__meter-fill" style={{ width: `${Math.round(micLevel * 100)}%` }} />
                </div>
                <Button variant="secondary" size="sm" onClick={requestMedia} disabled={camState === "requesting"}>
                  {camState === "requesting" ? "Requesting…" : camState === "live" ? "Retry" : "Enable camera & mic"}
                </Button>
              </div>
              {(camState === "denied" || camState === "unavailable") && (
                <p className="iv__warn">
                  Camera/mic unavailable — you can continue in text fallback mode. The interview and AI
                  evaluation still work; only the live preview is disabled.
                </p>
              )}
              <div className="iv__row">
                <Button variant="primary" size="lg" onClick={() => setStage("intro")}>
                  Continue to introduction
                </Button>
              </div>
            </div>
            <aside className="iv__card iv__side">
              <h3>What happens next</h3>
              <ol>
                <li>Q1: warm-up on a project you actually built</li>
                <li>Q2: counter-question probing your Q1 answer</li>
                <li>Q3: deep-dive — edge cases, trade-offs, failure modes</li>
                <li>Evidence report — corroborated vs needs validation</li>
              </ol>
              <p className="iv__fine">{session.privacy_notice}</p>
            </aside>
          </section>
        )}

        {stage === "intro" && session && (
          <section className="iv__card">
            <div className="iv__eyebrow">Introduction · {session.target_role}</div>
            <h2 className="iv__h2">How this interview works</h2>
            <ul className="iv__list">
              <li>One question at a time — I won&apos;t give away answers.</li>
              <li>Explain your own work: architecture, trade-offs, failure modes.</li>
              <li>Short vague answers get a focused follow-up, not a pass.</li>
              <li>Nothing here judges appearance — only the content of your answers.</li>
            </ul>
            <div className="iv__row">
              <Button variant="primary" size="lg" onClick={() => setStage("question")}>
                Start question 1 of {session.question_count}
              </Button>
            </div>
            <p className="iv__fine">{session.disclaimer}</p>
          </section>
        )}

        {(stage === "question" || stage === "evaluating") && current && session && (
          <section className="iv__grid">
            <div className="iv__card">
              <div className="iv__progress">
                <div className="iv__progress-fill" style={{ width: `${progress}%` }} />
              </div>
              <div className="iv__meta">
                <span>
                  Q{current.sequence} of {session.question_count} · {current.target_skill || "General"}
                </span>
                <span>{answeredCount}/{totalQuestions} answered</span>
                <span>{mmss}</span>
              </div>
              <h2 className="iv__q">{current.question}</h2>
              {current.is_follow_up && <span className="iv__chip">Adaptive follow-up</span>}
              <label className="iv__label">
                Your answer
                <textarea
                  className="iv__textarea"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  rows={7}
                  placeholder="Explain in your own words — architecture, reasoning, trade-offs…"
                  disabled={stage === "evaluating"}
                />
              </label>
              <div className="iv__row">
                <Button variant="secondary" size="sm" onClick={toggleDictation} disabled={stage === "evaluating"}>
                  {dictating ? "Stop dictation" : "🎙 Dictate answer"}
                </Button>
                <Button variant="primary" size="md" onClick={handleSubmit} disabled={stage === "evaluating" || !answer.trim()}>
                  {stage === "evaluating" ? "Evaluating…" : "Submit answer"}
                </Button>
                <Button variant="secondary" size="sm" onClick={handleComplete}>
                  Finish early
                </Button>
              </div>
              {audioFallback && (
                <p className="iv__warn">
                  Live dictation isn&apos;t supported in this browser — type your answer instead. Your typed
                  answer is evaluated identically.
                </p>
              )}
              {!session.ai_available && (
                <p className="iv__warn">
                  AI evaluation is not configured right now — your answer will be saved and marked pending
                  rather than scored.
                </p>
              )}
            </div>
            <aside className="iv__card iv__side">
              <h3>Presence</h3>
              <video ref={videoRef} className="iv__video iv__video--small" muted playsInline autoPlay />
              <p className="iv__fine">Preview only — never uploaded.</p>
              <div className="iv__meter-row">
                <span className="iv__meter-label">Mic</span>
                <div className="iv__meter">
                  <div className="iv__meter-fill" style={{ width: `${Math.round(micLevel * 100)}%` }} />
                </div>
              </div>
            </aside>
          </section>
        )}

        {stage === "feedback" && lastResult && (
          <section className="iv__card">
            <div className="iv__eyebrow">
              {lastResult.next_action === "complete" ? "Section complete" : `Next: Q${(lastResult.current_question?.sequence ?? 0)}`}
            </div>
            <h2 className="iv__h2">Evidence captured</h2>
            {lastResult.evaluation ? (
              <div className="iv__eval">
                <div className="iv__scores">
                  {(
                    [
                      ["Correctness", lastResult.evaluation.technical_correctness],
                      ["Depth", lastResult.evaluation.depth],
                      ["Reasoning", lastResult.evaluation.reasoning],
                      ["Corroboration", lastResult.evaluation.evidence_corroboration],
                    ] as Array<[string, number]>
                  ).map(([label, v]) => (
                    <div key={label} className="iv__score">
                      <div className="iv__score-v">{pct(v)}</div>
                      <div className="iv__score-l">{label}</div>
                    </div>
                  ))}
                </div>
                <p>{lastResult.evaluation.explanation}</p>
                {lastResult.evaluation.follow_up_needed && (
                  <p className="iv__warn">I&apos;ll probe this deeper with a follow-up question.</p>
                )}
                {lastResult.evaluation.contradiction > 0.5 && (
                  <p className="iv__warn">
                    This answer sits uneasily with your prior evidence — flagged for further validation,
                    not judged.
                  </p>
                )}
              </div>
            ) : (
              <p className="iv__warn">
                AI evaluation unavailable — your answer is saved as pending. {lastResult.note ?? ""}
                You can retry grading later; nothing was fabricated.
              </p>
            )}
            <div className="iv__row">
              <Button variant="primary" size="lg" onClick={handleNext}>
                {lastResult.next_action === "complete" ? "See my evidence report" : "Continue"}
              </Button>
            </div>
          </section>
        )}

        {stage === "completing" && (
          <section className="iv__card">
            <h2 className="iv__h2">Building your evidence report…</h2>
            <p className="iv__sub">Aggregating interview evidence into your skill profile.</p>
          </section>
        )}

        {stage === "report" && report && (
          <section>
            <div className="iv__card">
              <div className="iv__eyebrow">Interview evidence report · {report.target_role}</div>
              <h2 className="iv__h2">What the interview demonstrated</h2>
              <div className="iv__stats">
                <div><strong>{report.questions_answered}</strong> answers</div>
                <div><strong>{report.skills_evaluated.length}</strong> skills probed</div>
                <div><strong>{pct(report.overall_interview_confidence)}</strong> grading confidence</div>
              </div>
              <div className="iv__cols">
                <div>
                  <h3>Corroborated</h3>
                  {report.corroborated.length === 0 ? <p className="iv__fine">None yet.</p> : (
                    <ul>{report.corroborated.map((s) => <li key={s}>{s}</li>)}</ul>
                  )}
                </div>
                <div>
                  <h3>Needs further validation</h3>
                  {report.needs_validation.length === 0 ? <p className="iv__fine">None flagged.</p> : (
                    <ul>{report.needs_validation.map((s) => <li key={s}>{s}</li>)}</ul>
                  )}
                </div>
              </div>
            </div>
            <div className="iv__card">
              <h3>Per-skill evidence</h3>
              <table className="iv__table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>Before</th>
                    <th>Interview</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {report.skill_results.map((r) => (
                    <tr key={r.skill}>
                      <td><strong>{r.skill}</strong><br /><span className="iv__fine">{r.explanation}</span></td>
                      <td>{pct(r.proficiency_before)}</td>
                      <td>{pct(r.interview_signal)}</td>
                      <td><span className="iv__chip">{r.verdict.replace(/_/g, " ")}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {report.inconsistencies.length > 0 && (
              <div className="iv__card">
                <h3>Evidence inconsistencies</h3>
                <ul>
                  {report.inconsistencies.map((i) => (
                    <li key={i.skill}><strong>{i.skill}:</strong> {i.detail}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="iv__card">
              <h3>Recommended next actions</h3>
              <ol>
                {report.recommended_next_actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
              <p className="iv__fine">
                Roadmap impact is indirect by design: interview evidence → updated skill profile →
                existing gap calculation → existing roadmap generation on your next analysis run.
              </p>
              <div className="iv__row">
                <Link to="/analysis"><Button variant="primary" size="md">Re-run analysis</Button></Link>
                <Link to="/roadmap"><Button variant="secondary" size="md">View roadmap</Button></Link>
                <Link to="/dashboard"><Button variant="secondary" size="md">Dashboard</Button></Link>
              </div>
            </div>
          </section>
        )}
      </main>

      {liveInterviewSkill && (
        <InterviewModal
          skill={liveInterviewSkill}
          onClose={() => setLiveInterviewSkill(null)}
        />
      )}
    </div>
  );
}
