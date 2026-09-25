import { describe, it } from "node:test";
import assert from "node:assert";
import {
  buildDeck,
  deckStanding,
  KIND_LABEL,
  planSession,
  requeue,
  skillsInSession,
  type DeckSources,
  type RevisionCard,
} from "../src/lib/revision/deck.ts";
import { grade, newProgress, type CardProgress } from "../src/lib/revision/schedule.ts";

const T0 = new Date(2026, 8, 24, 10, 0, 0).getTime();

const sources: DeckSources = {
  role: "Full Stack Developer",
  skills: [
    {
      skill: "React",
      slug: "react",
      priority: 0.8,
      proficiency: 0.42,
      confidence: 0.3,
      capabilities: [
        {
          id: "state",
          title: "Managing component state",
          summary: "Hold state where it is used and lift it only when shared.",
          observable_abilities: ["Choose between local and lifted state", "Avoid redundant state"],
        },
        // Nothing to check yourself against, so no card
        { id: "empty", title: "Vague capability", summary: "Something woolly." },
      ],
      industry_expectations: [
        { capability_id: "state", title: "Predictable state", detail: "Teams expect state that can be reasoned about." },
      ],
      missing_capabilities: [
        { id: "testing", title: "Testing components", next_actions: ["Write a test for one component"], priority_category: "Critical" },
        // No next actions: nothing to tell you, so no card
        { id: "vague", title: "Something missing" },
      ],
      demonstrated_capabilities: [{ id: "state", title: "Managing component state" }],
      evidence_sources: [{ provider: "github", repository: "campus-rides" }],
    },
    { skill: "System Design", slug: "system_design", priority: 0.2, proficiency: 0.7, priority_category: "MODERATE", capabilities: [
      { id: "scale", title: "Scaling reads", observable_abilities: ["Add a cache", "Explain the read path"] },
    ] },
  ],
  tasks: [
    { id: "t1", title: "Write a test for one component", description: "Start with the smallest one.", skill_name: "React", week: 2, current: true },
    { id: "t2", title: "Read about sharding", skill_name: "System Design", week: 5, current: false },
    // No skill attached: nothing to file it under
    { id: "t3", title: "Orphan task", week: 5, current: false },
  ],
  dsa: [
    { id: "two-sum", title: "Two Sum", topic: "Arrays", pattern: "Hash map", difficulty: "Easy", why_it_matters: "Trades space for time.", solved: true },
    { id: "lru", title: "LRU Cache", topic: "Design", pattern: "Hash map + linked list", difficulty: "Hard", why_it_matters: "Order and lookup together.", solved: false },
    // No pattern: there is no answer to give
    { id: "mystery", title: "Mystery", topic: "Arrays", pattern: "", difficulty: "Easy", why_it_matters: "", solved: false },
  ],
};

const deck = buildDeck(sources);
const byId = (id: string) => deck.find((c) => c.id === id);

describe("the kinds of card INAURA asks", () => {
  it("asks a concept using the abilities you can check yourself against", () => {
    const card = byId("concept:react:state");
    assert.ok(card);
    assert.equal(card!.kind, "concept");
    assert.match(card!.question, /Managing component state/);
    assert.deepEqual(card!.points, ["Choose between local and lifted state", "Avoid redundant state"]);
  });

  it("asks what industry expects, answered by the benchmark behind it", () => {
    const card = byId("industry:react:state");
    assert.equal(card!.kind, "industry");
    assert.equal(card!.answer, "Teams expect state that can be reasoned about.");
  });

  it("asks about a gap, answered by what would close it", () => {
    const card = byId("gap:react:testing");
    assert.equal(card!.kind, "gap");
    assert.match(card!.question, /Testing components/);
    assert.deepEqual(card!.points, ["Write a test for one component"]);
    assert.match(card!.why, /critical/i, "the analysis's own priority should be quoted back");
  });

  it("asks what evidence you actually have, and says where INAURA found it", () => {
    const card = byId("evidence:react");
    assert.equal(card!.kind, "evidence");
    assert.match(card!.answer, /campus-rides/);
    assert.deepEqual(card!.points, ["Managing component state"]);
  });

  it("asks what your plan has you doing next", () => {
    const card = byId("roadmap:t1");
    assert.equal(card!.kind, "roadmap");
    assert.equal(card!.topic, "React");
    assert.equal(card!.answer, "Write a test for one component");
    assert.match(card!.why, /Week 2/);
    assert.match(card!.why, /where you are now/);
  });

  it("asks DSA by pattern, which is the thing worth recalling", () => {
    const card = byId("pattern:lru");
    assert.equal(card!.kind, "pattern");
    assert.equal(card!.answer, "Hash map + linked list");
    assert.match(card!.why, /unsolved/);
  });

  it("has a readable name for every kind it can produce", () => {
    for (const card of deck) {
      assert.ok(KIND_LABEL[card.kind], `${card.kind} has no label`);
    }
  });
});

describe("what never becomes a card", () => {
  it("skips a capability with no abilities behind it", () => {
    assert.equal(byId("concept:react:empty"), undefined);
  });

  it("skips a gap with nothing to tell you to do about it", () => {
    assert.equal(byId("gap:react:vague"), undefined);
  });

  it("skips a DSA question with no pattern to answer it", () => {
    assert.equal(byId("pattern:mystery"), undefined);
  });

  it("skips a roadmap task with no skill attached", () => {
    assert.equal(byId("roadmap:t3"), undefined);
  });

  it("builds nothing at all rather than filler when there is no data", () => {
    assert.deepEqual(buildDeck(), []);
    assert.deepEqual(buildDeck({ skills: [], dsa: [], tasks: [] }), []);
  });
});

describe("every card carries its reason", () => {
  it("tells you why you're seeing it, using real numbers", () => {
    for (const card of deck) {
      assert.ok(card.why.trim(), `${card.id} has no reason`);
    }
    assert.match(byId("concept:react:state")!.why, /42%/, "your actual level should be quoted");
    assert.match(byId("concept:react:state")!.why, /Full Stack Developer/, "against the actual role");
  });

  it("says when a skill is on this week's plan", () => {
    assert.match(byId("concept:react:state")!.why, /roadmap has you on this now/);
    assert.doesNotMatch(byId("concept:system_design:scale")!.why, /roadmap has you on this now/);
  });

  it("mentions low confidence only when confidence really is low", () => {
    assert.match(byId("concept:react:state")!.why, /little has confirmed it/);
    assert.doesNotMatch(byId("concept:system_design:scale")!.why, /little has confirmed it/);
  });

  it("gives every card a question, an answer and a skill", () => {
    for (const c of deck) {
      assert.ok(c.question.trim(), `${c.id} has no question`);
      assert.ok(c.answer.trim(), `${c.id} has no answer`);
      assert.ok(c.topic.trim(), `${c.id} has no topic`);
    }
  });

  it("has no two cards sharing an id", () => {
    const ids = deck.map((c) => c.id);
    assert.equal(new Set(ids).size, ids.length);
  });
});

describe("the level shown on a card face", () => {
  it("takes a gap's own priority, tidied into a label", () => {
    assert.equal(byId("gap:react:testing")!.level, "Critical");
  });

  it("falls back to the skill's priority for its other cards", () => {
    assert.equal(byId("concept:system_design:scale")!.level, "Moderate");
  });

  it("uses difficulty for a DSA question", () => {
    assert.equal(byId("pattern:lru")!.level, "Hard");
    assert.equal(byId("pattern:two-sum")!.level, "Easy");
  });

  it("uses the week for a roadmap card", () => {
    assert.equal(byId("roadmap:t1")!.level, "Week 2");
  });

  it("marks what you've already shown as proven", () => {
    assert.equal(byId("evidence:react")!.level, "Proven");
  });

  it("leaves it off rather than inventing one", () => {
    assert.equal(byId("concept:react:state")!.level, undefined, "React has no priority_category in the fixture");
  });
});

describe("which cards come first", () => {
  it("puts a gap above a concept on the same skill", () => {
    assert.ok(byId("gap:react:testing")!.weight > byId("concept:react:state")!.weight);
  });

  it("puts the skill your roadmap has you on above one it doesn't", () => {
    assert.ok(byId("concept:react:state")!.weight > byId("concept:system_design:scale")!.weight);
  });

  it("puts this week's roadmap task above a later one", () => {
    assert.ok(byId("roadmap:t1")!.weight > byId("roadmap:t2")!.weight);
  });

  it("puts a DSA question you haven't solved above one you have", () => {
    assert.ok(byId("pattern:lru")!.weight > byId("pattern:two-sum")!.weight);
  });

  it("ranks what you've already proved last, since it needs least work", () => {
    assert.ok(byId("evidence:react")!.weight < byId("gap:react:testing")!.weight);
  });

  it("introduces new cards heaviest first", () => {
    const plan = planSession(deck, {}, T0, { limit: 50, newLimit: 50 });
    const weights = plan.queue.map((c) => c.weight);
    assert.deepEqual(weights, [...weights].sort((a, b) => b - a));
  });
});

describe("planning a sitting", () => {
  const card = (id: string, weight = 1): RevisionCard => ({
    id, kind: "pattern", topic: "T", question: "q", answer: "a", points: [], why: "w", weight,
  });
  const many = Array.from({ length: 40 }, (_, i) => card(`c${i}`, 40 - i));

  it("caps the sitting, so it has an end", () => {
    assert.equal(planSession(many, {}, T0, { limit: 10, newLimit: 10 }).queue.length, 10);
  });

  it("rations new cards, so a first sitting isn't all strangers", () => {
    const plan = planSession(many, {}, T0, { limit: 20, newLimit: 5 });
    assert.equal(plan.queue.length, 5);
    assert.equal(plan.newCount, 5);
  });

  it("brings back what is due before meeting anyone new", () => {
    const progress: Record<string, CardProgress> = {};
    for (const id of ["c30", "c31"]) progress[id] = { ...newProgress(), seen: 1, dueAt: T0 - 1000 };
    const plan = planSession(many, progress, T0, { limit: 5, newLimit: 5 });
    assert.deepEqual(plan.queue.slice(0, 2).map((c) => c.id), ["c30", "c31"]);
    assert.equal(plan.dueCount, 2);
    assert.equal(plan.newCount, 3);
  });

  it("holds back the overflow and says how much", () => {
    const progress: Record<string, CardProgress> = {};
    for (const c of many) progress[c.id] = { ...newProgress(), seen: 1, dueAt: T0 - 1000 };
    const plan = planSession(many, progress, T0, { limit: 10 });
    assert.equal(plan.queue.length, 10);
    assert.equal(plan.heldBack, 30);
  });

  it("offers nothing when everything is scheduled ahead", () => {
    const progress: Record<string, CardProgress> = {};
    for (const c of many) progress[c.id] = grade(newProgress(), "got", T0);
    assert.equal(planSession(many, progress, T0, { limit: 10 }).queue.length, 0);
  });
});

describe("the focus panel", () => {
  it("counts the skills in a session, busiest first", () => {
    const make = (id: string, topic: string): RevisionCard => ({
      id, kind: "concept", topic, question: "q", answer: "a", points: [], why: "w", weight: 1,
    });
    const counted = skillsInSession([
      make("1", "React"), make("2", "SQL"), make("3", "React"), make("4", "React"), make("5", "SQL"),
    ]);
    assert.deepEqual(counted, [
      { topic: "React", count: 3 },
      { topic: "SQL", count: 2 },
    ]);
  });

  it("is empty for an empty session rather than throwing", () => {
    assert.deepEqual(skillsInSession([]), []);
  });
});

describe("a card you missed", () => {
  const cards = ["a", "b", "c", "d", "e", "f", "g"].map(
    (id): RevisionCard => ({ id, kind: "pattern", topic: "T", question: "q", answer: "a", points: [], why: "w", weight: 1 })
  );

  it("comes back later in the same sitting, not at the very next card", () => {
    const next = requeue(cards, cards[0], 4);
    assert.equal(next[0].id, "b");
    assert.equal(next[4].id, "a");
    assert.equal(next.length, cards.length, "it is moved, not added");
  });

  it("goes to the end when the sitting is nearly over", () => {
    assert.deepEqual(requeue(cards.slice(0, 3), cards[0], 4).map((c) => c.id), ["b", "c", "a"]);
  });

  it("never drops the card", () => {
    const next = requeue(cards, cards[2], 4);
    assert.equal(new Set(next.map((c) => c.id)).size, cards.length);
  });
});

describe("how the deck stands", () => {
  it("separates what is new, what is due, and what is known", () => {
    const cards = ["a", "b", "c", "d"].map(
      (id): RevisionCard => ({ id, kind: "pattern", topic: "T", question: "q", answer: "a", points: [], why: "w", weight: 1 })
    );
    let known = newProgress();
    for (let i = 0; i < 4; i++) known = grade(known, "got", T0);

    const standing = deckStanding(cards, { a: { ...newProgress(), seen: 1, dueAt: T0 - 1 }, b: known }, T0);
    assert.deepEqual(standing, { total: 4, due: 1, unseen: 2, learned: 1 });
  });
});
