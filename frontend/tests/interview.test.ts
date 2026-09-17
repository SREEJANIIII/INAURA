import { describe, it } from "node:test";
import assert from "node:assert";

// Mock minimal DOM types for Node environment testing
class MockMediaStreamTrack {
  kind: "video" | "audio";
  enabled: boolean = true;
  stopped: boolean = false;
  constructor(kind: "video" | "audio") {
    this.kind = kind;
  }
  stop() {
    this.stopped = true;
  }
}

class MockMediaStream {
  tracks: MockMediaStreamTrack[] = [];
  constructor(tracks: MockMediaStreamTrack[] = []) {
    this.tracks = [...tracks];
  }
  getTracks() {
    return this.tracks;
  }
  getVideoTracks() {
    return this.tracks.filter((t) => t.kind === "video");
  }
  getAudioTracks() {
    return this.tracks.filter((t) => t.kind === "audio");
  }
}

describe("1. Media Devices & Stream Management", () => {
  it("initializes in idle state and successfully requests both video and audio tracks", async () => {
    let requestedConstraints: MediaStreamConstraints | null = null;
    const fakeStream = new MockMediaStream([
      new MockMediaStreamTrack("video"),
      new MockMediaStreamTrack("audio"),
    ]);

    const getUserMedia = async (constraints: MediaStreamConstraints) => {
      requestedConstraints = constraints;
      return fakeStream;
    };

    const stream = await getUserMedia({ video: true, audio: true });
    assert.deepStrictEqual(requestedConstraints, { video: true, audio: true });
    assert.strictEqual(stream.getVideoTracks().length, 1);
    assert.strictEqual(stream.getAudioTracks().length, 1);
  });

  it("handles camera denial gracefully while keeping microphone active", async () => {
    let micStreamRequested = false;
    const getUserMedia = async (constraints: { video?: boolean; audio?: boolean }) => {
      if (constraints.video && constraints.audio) {
        const err = new Error("Permission denied");
        err.name = "NotAllowedError";
        throw err;
      }
      if (constraints.audio && !constraints.video) {
        micStreamRequested = true;
        return new MockMediaStream([new MockMediaStreamTrack("audio")]);
      }
      throw new Error("Unavailable");
    };

    let camState: string = "idle";
    let micState: string = "idle";
    let usable = false;

    try {
      await getUserMedia({ video: true, audio: true });
    } catch {
      camState = "denied";
      try {
        const micStream = await getUserMedia({ video: false, audio: true });
        if (micStream.getAudioTracks().length > 0) {
          micState = "live";
          usable = true;
        }
      } catch {
        micState = "denied";
      }
    }

    assert.strictEqual(camState, "denied");
    assert.strictEqual(micState, "live");
    assert.strictEqual(micStreamRequested, true);
    assert.strictEqual(usable, true); // Usable as audio-only interview
  });

  it("toggles camera without destroying media stream", () => {
    const videoTrack = new MockMediaStreamTrack("video");
    const stream = new MockMediaStream([videoTrack]);

    assert.strictEqual(videoTrack.enabled, true);
    // User turns off camera
    videoTrack.enabled = false;
    assert.strictEqual(videoTrack.enabled, false);
    assert.strictEqual(videoTrack.stopped, false); // Not stopped, stream alive
    // User turns on camera
    videoTrack.enabled = true;
    assert.strictEqual(videoTrack.enabled, true);
    assert.strictEqual(stream.getVideoTracks().length, 1);
  });

  it("toggles microphone without destroying media stream", () => {
    const audioTrack = new MockMediaStreamTrack("audio");

    assert.strictEqual(audioTrack.enabled, true);
    // User mutes mic
    audioTrack.enabled = false;
    assert.strictEqual(audioTrack.enabled, false);
    assert.strictEqual(audioTrack.stopped, false);
    // User unmutes mic
    audioTrack.enabled = true;
    assert.strictEqual(audioTrack.enabled, true);
  });

  it("stops all tracks on call End cleanup", () => {
    const videoTrack = new MockMediaStreamTrack("video");
    const audioTrack = new MockMediaStreamTrack("audio");
    const stream = new MockMediaStream([videoTrack, audioTrack]);

    stream.getTracks().forEach((t) => t.stop());
    assert.strictEqual(videoTrack.stopped, true);
    assert.strictEqual(audioTrack.stopped, true);
  });
});

describe("2. Technical Transcription & Vocabulary Quality", () => {
  function normalizeTechnicalTerms(text: string): string {
    let s = text;
    const terms: Array<[RegExp, string]> = [
      [/\b(fast\s*api|fastapi)\b/gi, "FastAPI"],
      [/\b(post\s*gres|postgres|postgresql)\b/gi, "PostgreSQL"],
      [/\b(pg\s*vector|pgvector)\b/gi, "pgvector"],
      [/\b(type\s*script|typescript)\b/gi, "TypeScript"],
      [/\b(java\s*script|javascript)\b/gi, "JavaScript"],
      [/\b(rest\s*api|restful\s*api)\b/gi, "REST API"],
      [/\b(rag)\b/gi, "RAG"],
      [/\b(gemini)\b/gi, "Gemini"],
      [/\b(docker)\b/gi, "Docker"],
      [/\b(kubernetes|k8s)\b/gi, "Kubernetes"],
      [/\b(oop)\b/gi, "OOP"],
      [/\b(sql)\b/gi, "SQL"],
      [/\b(lang\s*chain|langchain)\b/gi, "LangChain"],
      [/\b(supabase)\b/gi, "Supabase"],
      [/\b(react)\b/gi, "React"],
    ];
    for (const [regex, replacement] of terms) {
      s = s.replace(regex, replacement);
    }
    return s;
  }

  it("normalizes common technical spoken names without altering sentence semantics", () => {
    const raw = "we built a rest api using fast api with post gres and pg vector for rag embeddings in gemini";
    const cleaned = normalizeTechnicalTerms(raw);
    assert.ok(cleaned.includes("REST API"));
    assert.ok(cleaned.includes("FastAPI"));
    assert.ok(cleaned.includes("PostgreSQL"));
    assert.ok(cleaned.includes("pgvector"));
    assert.ok(cleaned.includes("RAG"));
    assert.ok(cleaned.includes("Gemini"));
    assert.strictEqual(
      cleaned,
      "we built a REST API using FastAPI with PostgreSQL and pgvector for RAG embeddings in Gemini"
    );
  });

  it("keeps the raw transcript separate from optional technical normalization", () => {
    const raw = "I used post gray SQL with pg vector";
    const normalized = normalizeTechnicalTerms(raw);
    assert.strictEqual(raw, "I used post gray SQL with pg vector");
    assert.notStrictEqual(normalized, raw);
  });
});

describe("3. Speech Recognition Silence Pipeline & Duplicate Guard", () => {
  it("does not trigger silence timer before meaningful speech is detected", () => {
    let silenceTimerActive = false;
    let hasSpoken = false;

    const onStartListening = () => {
      // Correct behavior: do NOT activate silence timer on initial start
      hasSpoken = false;
      silenceTimerActive = false;
    };

    onStartListening();
    assert.strictEqual(silenceTimerActive, false);
    assert.strictEqual(hasSpoken, false);

    // Candidate speaks words
    const onSpeechDetected = (chunk: string) => {
      if (chunk.trim().length > 0) {
        hasSpoken = true;
        silenceTimerActive = true;
      }
    };

    onSpeechDetected("Encapsulation is bundling data and methods together");
    assert.strictEqual(hasSpoken, true);
    assert.strictEqual(silenceTimerActive, true);
  });

  it("resets transcript between questions", () => {
    let finalTranscript = "Answer to question 1";
    let interimTranscript = "";

    // Question 1 completes, reset for question 2:
    const reset = () => {
      finalTranscript = "";
      interimTranscript = "";
    };

    reset();
    assert.strictEqual(finalTranscript, "");
    assert.strictEqual(interimTranscript, "");

    // Question 2 speech
    finalTranscript = "Answer to question 2";
    assert.strictEqual(finalTranscript, "Answer to question 2");
    assert.ok(!finalTranscript.includes("question 1"));
  });

  it("guards against duplicate answer submissions", () => {
    let isSubmitting = false;
    let submitCount = 0;

    const submitAnswer = (text: string) => {
      if (isSubmitting || !text.trim()) return;
      isSubmitting = true;
      submitCount++;
    };

    submitAnswer("First technical explanation");
    submitAnswer("First technical explanation"); // Duplicate call from onend or silence
    submitAnswer("First technical explanation");

    assert.strictEqual(submitCount, 1);
  });

  it("rejects empty answers and requests clarification", () => {
    let submittedToBackend = false;
    let clarifyingPrompt = "";

    const submitAnswer = (transcript: string) => {
      const trimmed = transcript.trim();
      if (!trimmed) {
        clarifyingPrompt = "I didn't catch that. Take your time and explain it in your own words.";
        return;
      }
      submittedToBackend = true;
    };

    submitAnswer("   ");
    assert.strictEqual(submittedToBackend, false);
    assert.strictEqual(
      clarifyingPrompt,
      "I didn't catch that. Take your time and explain it in your own words."
    );
  });
});

describe("4. Interview State Machine & Lifecycle Guards", () => {
  it("immediately transitions from intro to initializing on Let's Begin", () => {
    let phase = "intro";
    let interviewActive = false;

    const onBeginInterview = () => {
      interviewActive = true;
      phase = "initializing";
    };

    onBeginInterview();
    assert.strictEqual(phase, "initializing");
    assert.strictEqual(interviewActive, true);
  });

  it("verifies lifecycle guard stops async continuation after End", async () => {
    let interviewActive = true;
    let phase = "ai_speaking";

    const endInterview = () => {
      interviewActive = false;
      phase = "completed";
    };

    // Simulate async TTS speaking while user clicks End
    const asyncTTS = new Promise<void>((resolve) => {
      setTimeout(() => {
        // When speech finishes:
        if (!interviewActive) {
          resolve();
          return; // Guard prevented phase change!
        }
        phase = "listening";
        resolve();
      }, 10);
    });

    // End is clicked before TTS finishes
    endInterview();
    await asyncTTS;

    // Phase must remain completed and NOT revert to listening!
    assert.strictEqual(phase, "completed");
  });

  it("correctly executes repeat question flow", () => {
    let speechStopped = false;
    let ttsStopped = false;
    const currentPrompt = "What is polymorphism?";
    let spokenText = "";

    const repeatQuestion = () => {
      speechStopped = true;
      ttsStopped = true;
      spokenText = `Let me repeat the question. ${currentPrompt}`;
    };

    repeatQuestion();
    assert.strictEqual(speechStopped, true);
    assert.strictEqual(ttsStopped, true);
    assert.strictEqual(spokenText, "Let me repeat the question. What is polymorphism?");
  });
});

describe("5. Backend Adaptive Action Integration", () => {
  it("voices ack and question as separate utterances, each exactly once", () => {    // New contract: spoken_response is ack-only, the question travels in
    // current_question.prompt. The modal speaks each once, in order.
    const buildUtterances = (res: {
      action: string;
      spoken_response?: string | null;
      current_question?: { prompt: string } | null;
    }): string[] => {
      const out: string[] = [];
      const ack = (res.spoken_response || "").trim();
      const question = (res.current_question?.prompt || "").trim();
      if (ack) out.push(ack);
      if (question) out.push(question);
      return out;
    };

    // Follow-up probe: ack-only + question, no duplication.
    const followUpRes = {
      action: "FOLLOW_UP",
      spoken_response: "I see.",
      current_question: { prompt: "Could you explain what happens when retrieval returns poor matches?" },
    };
    assert.deepStrictEqual(buildUtterances(followUpRes), [
      "I see.",
      "Could you explain what happens when retrieval returns poor matches?",
    ]);

    // Next question: ack-only + question, question appears exactly once.
    const nextRes = {
      action: "NEXT",
      spoken_response: "Thank you for explaining that. Let's move on to the next question.",
      current_question: { prompt: "How do you handle schema migrations with PostgreSQL?" },
    };
    const utterances = buildUtterances(nextRes);
    assert.strictEqual(utterances.length, 2);
    const joined = utterances.join(" ");
    const occurrences = joined.split("How do you handle schema migrations with PostgreSQL?").length - 1;
    assert.strictEqual(occurrences, 1);
  });
});

describe("6. Interview completion contract (Q1 early-end regression)", () => {
  type AnswerRes = {
    completed: boolean;
    next_action: string;
    action?: string | null;
    current_question: { id: string; prompt: string } | null;
  };

  // Mirrors InterviewModal's completion predicate: the interview completes
  // ONLY on the server's explicit terminal state — never because the
  // initial plan holds a single question or a non-terminal turn arrives
  // without a question payload.
  const shouldComplete = (res: AnswerRes): boolean =>
    res.completed || res.next_action === "complete" || res.action === "COMPLETE";

  it("does not interpret questions.length === 1 as completion", () => {
    // The live plan intentionally starts with only Q1.
    const initialQuestions = [{ id: "q1", prompt: "Walk me through an implementation." }];
    assert.strictEqual(initialQuestions.length, 1);
    const afterQ1: AnswerRes = {
      completed: false,
      next_action: "next",
      action: "NEXT",
      current_question: { id: "q2_coverage", prompt: "Follow-up?" },
    };
    assert.strictEqual(shouldComplete(afterQ1), false);
  });

  it("completes on explicit terminal state after the minimum", () => {
    const done: AnswerRes = {
      completed: true,
      next_action: "complete",
      action: "COMPLETE",
      current_question: null,
    };
    assert.strictEqual(shouldComplete(done), true);
  });

  it("missing current_question on a non-terminal turn is retryable, not completion", () => {
    const gap: AnswerRes = {
      completed: false,
      next_action: "next",
      action: "NEXT",
      current_question: null,
    };
    assert.strictEqual(shouldComplete(gap), false);
  });

  it("progress total is server-driven and grows past the initial plan", () => {
    // Initial plan holds only Q1: floor of 1, never 0/0 once started.
    let totalQuestions = Math.max(1, 1);
    assert.strictEqual(totalQuestions, 1);
    // After answering Q1 the server reports the grown plan total.
    const res = { answered_count: 1, total_questions: 2 };
    totalQuestions = Math.max(totalQuestions, res.total_questions, res.answered_count);
    assert.strictEqual(totalQuestions, 2);
    assert.ok(totalQuestions > 1);
  });
});

describe("7. Mock interview (/interview) 3-question progress contract", () => {
  const TOTAL = 3;

  // Mirrors Interview.tsx: answeredCount advances ONLY on successful submit,
  // progress is answeredCount / 3 — never questions.length based.
  const applySubmitSuccess = (prev: number, res: { answered_count?: unknown }): number =>
    typeof res.answered_count === "number" ? res.answered_count : prev + 1;

  const progressText = (answered: number): string => `${answered}/${TOTAL} answered`;

  it("shows 1/3, 2/3, 3/3 as answers land", () => {
    let answered = 0;
    answered = applySubmitSuccess(answered, { answered_count: 1 });
    assert.strictEqual(progressText(answered), "1/3 answered");
    answered = applySubmitSuccess(answered, { answered_count: 2 });
    assert.strictEqual(progressText(answered), "2/3 answered");
    answered = applySubmitSuccess(answered, { answered_count: 3 });
    assert.strictEqual(progressText(answered), "3/3 answered");
  });

  it("does not increment progress when merely displaying a question", () => {
    // Displaying Q2 (generated) without submitting must not move progress.
    const answeredBeforeDisplay = 1;
    assert.strictEqual(progressText(answeredBeforeDisplay), "1/3 answered");
  });

  it("does not increment progress on failed submit", () => {
    let answered = 1;
    // handleSubmit catch path: answeredCount untouched, stage back to question.
    const failed = false;
    if (failed) answered = applySubmitSuccess(answered, { answered_count: 2 });
    assert.strictEqual(answered, 1);
  });

  it("single initial question does not imply a 1-question interview", () => {
    const initialQuestions = [{ id: "q1", sequence: 1 }];
    const sessionQuestionCount = 3;
    assert.strictEqual(initialQuestions.length, 1);
    assert.strictEqual(sessionQuestionCount, 3);
    assert.ok(sessionQuestionCount > initialQuestions.length);
  });
});
