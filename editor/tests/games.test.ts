// Every game's view against the launcher's exports of the seeded saves
// (tests/test_page.py's seeds: what the page shows for them is known) and
// against C64UltimaEditor's played disks.

import { test } from "node:test";
import assert from "node:assert/strict";
import { decode, encode, type Ucsv } from "../src/container/ucsv.ts";
import { viewOf } from "../src/games/index.ts";
import { allFields, type GameView, type Field } from "../src/games/model.ts";
import { GAMES, NO_FIXTURES, fixture, have } from "./fixtures.ts";

function get(v: GameView, id: string): unknown {
  const f = allFields(v).find(x => x.field.id === id);
  assert.ok(f, `no field ${id}`);
  return v.doc.value(f.field);
}

/** Enum fields whose byte is none of the choices -- in a real save, a sign
 *  that the table is wrong (shown, not failed, for unused roster places). */
function oddEnums(v: GameView): string[] {
  const out: string[] = [];
  for (const { path, field } of allFields(v)) {
    if (field.enc.t !== "enum" || !v.doc.has(field)) continue;
    const val = v.doc.value(field) as number;
    if (!field.enc.values.some(([k]) => k === val)) out.push(`${path} › ${field.label} = $${val.toString(16)}`);
  }
  return out;
}

test("the seeded saves read as the launcher page shows them", { skip: NO_FIXTURES }, () => {
  const v1 = viewOf(decode(fixture("u1.seq")));
  assert.equal(get(v1, "p1.name"), "Brenda");
  assert.equal(get(v1, "p1.hp"), 150);
  assert.equal(get(v1, "p1.food"), 200);
  assert.equal(get(v1, "ro0.name"), "Anselm");
  const v2 = viewOf(decode(fixture("u2.seq")));
  assert.equal(get(v2, "name"), "HAWKWI");
  assert.equal(get(v2, "hp"), 421);
  assert.equal(get(v2, "food"), 399);
  const v3 = viewOf(decode(fixture("u3.seq")));
  assert.deepEqual([0, 1, 2].map(k => [get(v3, `plrs${k}.name`), get(v3, `plrs${k}.hp`), get(v3, `plrs${k}.maxhp`)]),
    [["IOLO", 150, 150], ["SHAMINO", 42, 275], ["DUPRE", 1234, 2500]]);
  const v5 = viewOf(decode(fixture("u5.seq")));
  assert.deepEqual([0, 1, 2].map(k => [get(v5, `c${k}.name`), get(v5, `c${k}.hp`), get(v5, `c${k}.maxhp`)]),
    [["tester", 60, 60], ["Shamino", 5, 60], ["Iolo", 90, 90]]);
  assert.equal(get(v5, "c0.eq3"), 48, "the Avatar's Ankh");
  const v6 = viewOf(decode(fixture("u6.seq")));
  assert.deepEqual([0, 1, 2, 3].map(k => [get(v6, `c${k}.name`), get(v6, `c${k}.hp`), get(v6, `c${k}.maxhp`)]),
    [["Tester", 90, 90], ["Dupre", 61, 96], ["Shamino", 47, 90], ["Iolo", 90, 90]]);
});

test("every field of a real save reads, and every choice is known", { skip: NO_FIXTURES }, () => {
  for (const g of GAMES) {
    const v = viewOf(decode(fixture(`${g}.seq`)));
    for (const { path, field } of allFields(v)) {
      const missing = !v.doc.has(field);
      // U1's empty slot P0 is not in the file (U6's sectors not in it read as the original disk's)
      const expected = g === "u1" && field.area === "p0";
      assert.equal(missing, expected, `${g}: ${path} › ${field.label}`);
    }
    // U2's and U3's seeds are made up (a name, HP, food): their choices are checked on real disks below
    if (g === "u2" || g === "u3") continue;
    const presentOnly = oddEnums(v).filter(s => !/Roster place|Place \d|Character \d/.test(s));
    assert.deepEqual(presentOnly, [], g);
  }
});

test("field ids are unique within a game", () => {
  for (const g of GAMES) {
    if (!have(`${g}.seq`)) continue;
    const ids = allFields(viewOf(decode(fixture(`${g}.seq`)))).map(x => x.field.id);
    const dup = ids.filter((id, k) => ids.indexOf(id) !== k);
    assert.deepEqual(dup, [], g);
  }
});

test("an edit of any field changes only its own bytes", { skip: NO_FIXTURES }, () => {
  for (const g of GAMES) {
    const raw = fixture(`${g}.seq`);
    const save = decode(raw);
    const v = viewOf(save);
    for (const { field } of allFields(v)) {
      if (field.readOnly || !v.doc.has(field)) continue;
      const val = v.doc.value(field);
      const next = alternative(field, val);
      if (next === undefined) continue;
      v.doc.set(field, next);
      assert.equal(v.doc.value(field), next, `${g} ${field.id}`);
      v.doc.undo();
      assert.equal(v.doc.value(field), val, `${g} ${field.id} undone`);
    }
    assert.deepEqual(encode(save), raw, `${g}: all undone`);
  }
});

function alternative(f: Field, v: unknown): number | string | boolean | undefined {
  const e = f.enc;
  if (e.t === "flag" || e.t === "nonzero") return !v;
  if (e.t === "enum") return e.values.map(([k]) => k).find(k => k !== v);
  if (e.t === "text") return v === "AB" ? "BA" : "AB";
  const n = Number(v);
  const max = f.max ?? 9;
  return n < max ? n + 1 : n - 1;
}

test("C64UltimaEditor's played disks read sensibly", () => {
  const sec = (img: Uint8Array, t: number, s: number) => {
    let o = 0;
    for (let k = 1; k < t; k++) o += k <= 17 ? 21 : k <= 24 ? 19 : k <= 30 ? 18 : 17;
    return img.slice((o + s) * 256, (o + s) * 256 + 256);
  };
  if (have("zoggins_u2.d64")) {
    const img = fixture("zoggins_u2.d64");
    const slots = Array.from({ length: 12 }, () => new Uint8Array(256));
    slots[11] = sec(img, 35, 16);
    const v = viewOf({ game: 2, version: 1, slots, records: [] } as Ucsv);
    assert.ok((get(v, "name") as string).length > 0);
    assert.deepEqual(oddEnums(v), []);
  }
  if (have("zoggins_u3.d64")) {
    const img = fixture("zoggins_u3.d64");
    const join = (t: number, from: number, n: number) => {
      const out = new Uint8Array(256 * n);
      for (let k = 0; k < n; k++) out.set(sec(img, t, from + k), 256 * k);
      return out;
    };
    const save: Ucsv = { game: 3, version: 1, records: [],
      slots: [join(15, 2, 16), join(15, 18, 1), join(16, 12, 5), join(16, 17, 1), join(16, 18, 1)] };
    const v = viewOf(save);
    assert.deepEqual([0, 1, 2, 3].map(k => get(v, `plrs${k}.name`)), ["ZUB", "ZARG", "ZOGGINS", "ZALOS"]);
    assert.deepEqual([0, 1, 2, 3].map(k => get(v, `member${k}`)), [5, 3, 1, 4], "1-based roster places");
    assert.equal(get(v, "rost4.name"), "ZUB");
    assert.deepEqual(oddEnums(v).filter(s => !/Roster place/.test(s)), []);
  }
});
