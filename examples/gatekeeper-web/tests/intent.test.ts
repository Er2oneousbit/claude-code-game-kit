// ---------------------------------------------------------------------------
// intent.test.ts
// Purpose : The model-output gate (SOP-15 step 6): recorded labels and lines, good and
//           broken, must be accepted or rejected exactly as expected (the same fixtures
//           the Godot version tests); and the keyword fallback classifies the obvious cases.
//           No live model in tests.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): the grammar test checks "nothing else" too
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { INTENT_GRAMMAR, INTENTS, keywordIntent, MAX_LINE, parseLabel, parseLine } from "../src/core/intent";
import recorded from "./fixtures/recorded.json";

describe("parseLabel on recorded classifier outputs", () => {
  for (const c of recorded.labels) it(c.name, () => expect(parseLabel(c.raw)).toBe(c.expect));
});

describe("parseLine on recorded speaker outputs", () => {
  for (const c of recorded.lines) it(c.name, () => expect(parseLine(c.raw)).toBe(c.expect));

  it("cuts long lines instead of trusting them", () => {
    expect(parseLine("A".repeat(1000))!.length).toBeLessThanOrEqual(MAX_LINE);
  });
});

describe("the classifier grammar", () => {
  it("lists every intent and nothing else", () => {
    expect(INTENT_GRAMMAR.startsWith("root ::= ")).toBe(true);
    const alternatives = INTENT_GRAMMAR.slice("root ::= ".length).split(" | ").map((a) => JSON.parse(a) as string);
    expect(alternatives).toEqual([...INTENTS]);
  });
});

describe("keywordIntent (no-model fallback)", () => {
  const cases: [string, string][] = [
    ["Hello there!", "greeting"],
    ["Captain Wren sent me.", "mentions_captain"],
    ["Here, take some gold.", "bribe"],
    ["Open it or I'll break your nose.", "threat"],
    ["You look very strong today.", "flattery"],
    ["That armor looks well kept.", "flattery"], // missed by the first keyword list: lost a scripted game
    ["Why is the gate closed?", "question"],
    ["Banana.", "other"],
  ];
  for (const [text, intent] of cases) it(`${JSON.stringify(text)} -> ${intent}`, () => expect(keywordIntent(text)).toBe(intent));

  it("threats win over everything else in the same sentence", () => {
    expect(keywordIntent("Hello captain, open up or I will hurt you")).toBe("threat");
  });
});
