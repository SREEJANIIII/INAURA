import { describe, it } from "node:test";
import assert from "node:assert";
import { buildIndex, PAGES, search, type SearchResult } from "../src/components/search/searchIndex.ts";
import { SEARCH_SUGGESTIONS, shuffled } from "../src/components/search/suggestions.ts";

const sources = {
  roles: [
    { id: "full-stack-developer", title: "Full Stack Developer", description: "Builds both sides of a web app." },
    { id: "backend-developer", title: "Backend Developer", description: "Builds APIs and services." },
  ],
  careerId: "full-stack-developer",
  skills: [
    { id: "react", name: "React", category: "Frontend" },
    { id: "postgresql", name: "PostgreSQL", category: "Databases" },
  ],
  gaps: [{ skill: "Docker" }],
  projects: [{ id: "p1", name: "Campus Ride Share", technologies: ["React", "Node"] }],
  certificates: [{ id: "c1", name: "AWS Cloud Practitioner", issuer: "Amazon" }],
  resources: [{ id: "r1", title: "MDN — Using the Fetch API", skill: "JavaScript" }],
  weeks: [
    { id: "w1", number: 1, title: "Foundations", tasks: [{ id: "t1", title: "Build a REST API", skill: "Node" }] },
  ],
};

const index = buildIndex(sources);
const first = (q: string) => search(q, index)[0];
const labels = (q: string) => search(q, index).map((r) => r.label);

describe("what the search can find", () => {
  it("finds a page by its name", () => {
    assert.equal(first("roadmap")?.to, "/roadmap");
    assert.equal(first("mock interview")?.to, "/interview");
    assert.equal(first("revision")?.to, "/revision");
  });

  it("finds a page by what people actually call it", () => {
    assert.equal(first("cv")?.to, "/resume/ats-tester");
    assert.equal(first("resume")?.to, "/resume/ats-tester");
    assert.equal(first("flashcards")?.to, "/revision");
    assert.equal(first("github")?.to, "/analysis");
  });

  it("finds a career and links to its track", () => {
    assert.equal(first("full stack")?.to, "/career-track/full-stack-developer");
    assert.equal(first("backend")?.to, "/career-track/backend-developer");
  });

  it("finds a skill and links to it inside the current career track", () => {
    assert.equal(first("react")?.to, "/career-track/full-stack-developer/react");
    assert.equal(first("postgres")?.to, "/career-track/full-stack-developer/postgresql");
  });

  it("finds your own projects, certificates and roadmap tasks", () => {
    assert.equal(first("campus ride")?.to, "/analysis#projects");
    assert.equal(first("aws")?.to, "/analysis#certifications");
    assert.equal(first("rest api")?.to, "/roadmap");
    assert.equal(first("foundations")?.to, "/roadmap");
  });

  it("finds a gap by the skill it's about", () => {
    const docker = search("docker", index).find((r) => r.kind === "Gap");
    assert.equal(docker?.to, "/analysis/results#priority-gaps");
  });

  it("leaves skills out until it knows which career track they belong to", () => {
    const noCareer = buildIndex({ ...sources, careerId: undefined });
    assert.ok(!search("react", noCareer).some((r) => r.kind === "Skill"));
    // The project that uses React is still findable
    assert.ok(search("react", noCareer).some((r) => r.kind === "Project"));
  });

  it("works before any of your data has loaded, on pages alone", () => {
    const bare = buildIndex();
    assert.deepEqual(bare, PAGES);
    assert.equal(search("roadmap", bare)[0]?.to, "/roadmap");
  });
});

describe("how results are ordered", () => {
  it("puts a name you typed in full above something that merely mentions it", () => {
    assert.equal(first("react")?.kind, "Skill");
  });

  it("matches the start of any word, so short queries land", () => {
    assert.ok(labels("int").includes("Mock Interview"));
    assert.ok(labels("dev").includes("Full Stack Developer"));
  });

  it("narrows as you add words rather than widening", () => {
    const one = search("developer", index).length;
    const two = search("backend developer", index).length;
    assert.ok(two < one, `"backend developer" (${two}) should be narrower than "developer" (${one})`);
    assert.equal(first("backend developer")?.label, "Backend Developer");
  });

  it("returns nothing for an empty query, so the panel stays shut", () => {
    assert.deepEqual(search("", index), []);
    assert.deepEqual(search("   ", index), []);
  });

  it("returns nothing when there's genuinely no match", () => {
    assert.deepEqual(search("zzzznothing", index), []);
  });

  it("ignores case and stray spacing", () => {
    assert.equal(first("  FULL   STACK  ")?.label, "Full Stack Developer");
  });

  it("caps how many it shows, so the panel stays a sensible size", () => {
    assert.ok(search("a", index, 5).length <= 5);
    assert.ok(search("e", index).length <= 8);
  });

  it("survives characters that mean something in a pattern", () => {
    assert.doesNotThrow(() => search("c++ (a) [b] *", index));
    const plus = buildIndex({ ...sources, skills: [{ id: "c-plus-plus", name: "C++" }] });
    assert.equal(search("c++", plus)[0]?.label, "C++");
  });

  it("gives every result somewhere to go", () => {
    for (const item of index) {
      assert.ok(item.to.startsWith("/"), `${item.label} has no destination`);
      assert.ok(item.label.trim(), "a result has no label");
    }
  });

  it("has no two results sharing an id", () => {
    const ids = index.map((i: SearchResult) => i.id);
    assert.equal(new Set(ids).size, ids.length);
  });
});

describe("placeholder suggestions", () => {
  it("offers more than the three it used to", () => {
    assert.ok(SEARCH_SUGGESTIONS.length >= 10);
  });

  it("only suggests things the search can actually find", () => {
    const all = buildIndex(sources);
    for (const word of SEARCH_SUGGESTIONS) {
      assert.ok(search(word, all).length > 0, `nothing found for the suggested "${word}"`);
    }
  });

  it("shuffles into a different order without losing or repeating any", () => {
    const order = shuffled(SEARCH_SUGGESTIONS, mulberry(7));
    assert.deepEqual([...order].sort(), [...SEARCH_SUGGESTIONS].sort());
    assert.notDeepEqual(order, [...SEARCH_SUGGESTIONS]);
  });

  it("leaves the original list untouched", () => {
    const before = [...SEARCH_SUGGESTIONS];
    shuffled(SEARCH_SUGGESTIONS, mulberry(3));
    assert.deepEqual([...SEARCH_SUGGESTIONS], before);
  });
});

/** A small seeded random, so the shuffle tests are repeatable */
function mulberry(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
