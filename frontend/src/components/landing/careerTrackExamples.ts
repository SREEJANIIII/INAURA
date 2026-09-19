/**
 * Example career tracks for the landing page's Career Track showcase: one per career INAURA
 * has industry benchmarks for (backend/app/services/industry_roles.py). They're illustrations,
 * not real students' data, shaped like the real Career Track: phases of skills, each with a
 * level now and the level the role expects.
 */
import { levelName } from "../career-track/careerTrackModel";

export type ExampleSkill = {
  name: string;
  /** Level now, 0–100 */
  now: number;
  /** Level the role expects, 0–100 */
  need: number;
  status: "ready" | "current" | "next" | "locked";
  levels: string;
  label: string;
};

export type ExamplePhase = { title: string; state: "done" | "active" | "locked"; skills: ExampleSkill[] };

export type ExampleTrack = { role: string; readiness: number; phases: ExamplePhase[]; unlocks: number };

type Seed = [name: string, now: number, need: number];

/** Foundation is done, the core stack is in progress, the advanced phase opens after it */
function track(role: string, readiness: number, unlocks: number, foundation: Seed[], core: Seed[], advanced: string[]): ExampleTrack {
  const [first] = core;
  return {
    role,
    readiness,
    unlocks,
    phases: [
      {
        title: "Foundation",
        state: "done",
        skills: foundation.map(([name, now, need]) => ({
          name,
          now,
          need,
          status: "ready",
          levels: `${levelName(now)} · bar met`,
          label: "Ready",
        })),
      },
      {
        title: "Core stack",
        state: "active",
        skills: core.map(([name, now, need], i) => ({
          name,
          now,
          need,
          status: i === 0 ? "current" : "next",
          levels: `${levelName(now)} → ${levelName(need)}`,
          label: `${need - now}% to go`,
        })),
      },
      {
        title: "Advanced",
        state: "locked",
        skills: advanced.map((name) => ({
          name,
          now: 0,
          need: 65,
          status: "locked",
          levels: `After ${first[0]}`,
          label: "Locked",
        })),
      },
    ],
  };
}

export const EXAMPLE_TRACKS: ExampleTrack[] = [
  track("Software Engineer", 61, 2, [["Programming fundamentals", 80, 70], ["Data structures & algorithms", 74, 70]], [["System design", 45, 70], ["Databases & SQL", 40, 65]], ["Testing", "Cloud & deployment"]),
  track("Frontend Developer", 58, 1, [["JavaScript", 78, 70], ["Git & version control", 62, 55]], [["React", 52, 75], ["TypeScript", 30, 60]], ["Architecture & quality", "Testing"]),
  track("Backend Developer", 54, 1, [["Python", 76, 70], ["Git & version control", 64, 55]], [["REST API design", 48, 72], ["SQL & databases", 42, 70]], ["Caching & scalability", "Security"]),
  track("Full Stack Developer", 49, 1, [["JavaScript", 72, 70], ["HTML & CSS", 80, 65]], [["React", 50, 72], ["Node.js & APIs", 34, 68]], ["Deployment & CI/CD", "Testing"]),
  track("Mobile Developer", 46, 1, [["Programming fundamentals", 72, 65], ["Git & version control", 60, 55]], [["Mobile UI frameworks", 40, 72], ["State management", 30, 65]], ["App performance", "Publishing & release"]),
  track("Data Analyst", 64, 2, [["Spreadsheets", 82, 70], ["SQL", 74, 70]], [["Data visualization", 55, 72], ["Statistics", 46, 70]], ["Python for analysis", "Dashboards & BI"]),
  track("Data Scientist", 52, 1, [["Python", 78, 72], ["Statistics", 70, 68]], [["Machine learning", 44, 72], ["Data wrangling", 50, 70]], ["Model evaluation", "Experiment design"]),
  track("Machine Learning Engineer", 44, 0, [["Python", 80, 72], ["Linear algebra", 68, 65]], [["Deep learning", 36, 72], ["ML pipelines", 28, 68]], ["Model deployment", "Scalable training"]),
  track("DevOps Engineer", 51, 1, [["Linux", 76, 70], ["Networking", 66, 60]], [["CI/CD pipelines", 44, 72], ["Containers", 38, 70]], ["Kubernetes", "Observability"]),
  track("Cloud Engineer", 47, 1, [["Linux", 72, 68], ["Networking", 64, 62]], [["Cloud platforms", 40, 72], ["Infrastructure as code", 30, 68]], ["Cloud security", "Cost & scaling"]),
  track("Cybersecurity Engineer", 42, 0, [["Networking", 74, 70], ["Linux", 68, 65]], [["Security fundamentals", 42, 72], ["Threat analysis", 30, 68]], ["Penetration testing", "Incident response"]),
];

export const DEFAULT_ROLE = "Frontend Developer";
