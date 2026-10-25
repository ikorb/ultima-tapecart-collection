// The searchable dropdown's filter: what a typed word finds, and in which order.

import { test } from "node:test";
import assert from "node:assert/strict";
import { matches } from "../src/ui/combo.ts";
import { OBJECTS } from "../src/games/u6names.ts";

const OBJ: [number, string][] = OBJECTS.map((n, k) => [k, k === 0 ? "—" : n]);
const names = (q: string) => matches(OBJ, q).map(([, n]) => n);

test("a word's start comes before the same letters inside a word", () => {
  const r = names("sw");
  assert.ok(r.length > 1);
  assert.equal(r[0], "sword");
  assert.ok(r.every(n => n.toLowerCase().includes("sw")));
  const first = r.findIndex(n => !/(^|[\s(/-])sw/i.test(n));
  if (first >= 0) assert.ok(r.slice(first).every(n => !/(^|[\s(/-])sw/i.test(n)), "starts first, then the rest");
});

test("case does not matter, nothing typed is everything, nothing found is nothing", () => {
  assert.deepEqual(names("ORB OF"), ["Orb of the Moons"]);
  assert.equal(matches(OBJ, "  ").length, OBJ.length);
  assert.deepEqual(names("xyzzy"), []);
});

test("a byte in hex or decimal finds that choice; the empty one answers to its words", () => {
  assert.deepEqual(matches(OBJ, "$12").map(([k]) => k), [0x12]);
  assert.deepEqual(matches(OBJ, "#18").map(([k]) => k), [18]);
  assert.deepEqual(matches(OBJ, "$ff"), []);
  for (const w of ["empty", "nothing", "none"]) assert.equal(matches(OBJ, w)[0][0], 0, w);
});
