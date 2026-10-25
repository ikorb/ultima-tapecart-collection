// Ultima I's and III's rosters: a character copied from another place, a
// character deleted, as the game itself frees a place; one undo step each,
// and undo puts every byte back (an Ultima I file the copy added goes again).

import { test } from "node:test";
import assert from "node:assert/strict";
import { decode, encode } from "../src/container/ucsv.ts";
import { viewOf } from "../src/games/index.ts";
import type { GameView, RecordDef } from "../src/games/model.ts";
import { NO_FIXTURES, fixture } from "./fixtures.ts";

const load = (g: number) => { const raw = fixture(`u${g}.seq`); const save = decode(raw); return { raw, save, v: viewOf(save) }; };

function rec(v: GameView, tab: string, k: number): RecordDef {
  const s = v.tabs.find(t => t.title === tab)!.sections[0];
  assert.ok(s.kind === "records");
  return s.records[k];
}

function copyInto(v: GameView, r: RecordDef, from: RegExp): void {
  const c = r.menus![0].choices(v.doc).find(x => from.test(x.label));
  assert.ok(c, `${from}: ${r.menus![0].choices(v.doc).map(x => x.label).join(" | ")}`);
  assert.equal(c.disabled ?? null, null, c.label);
  v.doc.edit(c.run, c.label);
}

function del(v: GameView, r: RecordDef): void {
  const a = r.actions!.find(x => x.label === "Delete")!;
  assert.equal(a.disabled?.(v.doc) ?? null, null);
  v.doc.edit(w => a.run!(w, v.doc), a.label);
}

test("U1: a seat without a character file gets one by a copy, and loses it by the undo", { skip: NO_FIXTURES }, () => {
  const { raw, save, v } = load(1);
  assert.equal(save.slots[1], null);                    // the seed: seat 1 in RO, no P0
  const seat1 = rec(v, "Characters", 0);
  assert.equal(seat1.present!(v.doc), false);
  copyInto(v, seat1, /^Seat 2: /);
  assert.deepEqual(save.slots[1], save.slots[2]);
  assert.deepEqual(save.slots[0]!.subarray(0, 16), save.slots[0]!.subarray(16, 32));
  assert.equal(seat1.present!(v.doc), true);
  assert.equal(seat1.title(v.doc), rec(v, "Characters", 1).title(v.doc));
  const again = decode(encode(save));
  assert.deepEqual(again.slots[1], save.slots[2]);
  v.doc.undo();
  assert.equal(save.slots[1], null);
  assert.deepEqual(encode(save), raw);
});

test("U1: delete frees the seat as the game's terminate does; a free seat is no source", { skip: NO_FIXTURES }, () => {
  const { raw, save, v } = load(1);
  const seat3 = rec(v, "Characters", 2);
  const p2 = save.slots[3]!.slice();
  del(v, seat3);
  assert.equal(save.slots[0]![32], 0);
  assert.deepEqual(save.slots[0]!.subarray(33, 48), decode(raw).slots[0]!.subarray(33, 48));   // the name stays
  assert.deepEqual(save.slots[3], p2);                                                            // and the file
  assert.equal(seat3.present!(v.doc), false);
  assert.equal(seat3.title(v.doc), "Character 3");
  assert.equal(seat3.actions![0].disabled!(v.doc), "the seat is free");
  const from = rec(v, "Characters", 3).menus![0].choices(v.doc).find(c => c.label.startsWith("Seat 3"))!;
  assert.equal(from.disabled, "free");
  v.doc.undo();
  assert.deepEqual(encode(save), raw);
});

test("U3: a party member or a place copied into the roster, out of the party; delete zeroes the place", { skip: NO_FIXTURES }, () => {
  const { raw, save, v } = load(3);
  const rost = save.slots[2]!, plrs = save.slots[3]!;
  const place = (k: number) => rec(v, "Roster", k);
  assert.equal(place(0).present!(v.doc), false);
  const member = place(0).menus![0].choices(v.doc).filter(c => c.label.startsWith("Party member"));
  assert.equal(member.length, save.slots[4]![1]);                     // PRTY +1, the party's size
  copyInto(v, place(0), /^Party member 1: /);
  const want = plrs.slice(0, 64);
  want[0x10] = 0;
  assert.deepEqual(rost.subarray(0, 64), want);
  assert.equal(place(0).title(v.doc), rec(v, "Party", 0).title(v.doc));
  copyInto(v, place(4), /^Place 1: /);
  assert.deepEqual(rost.subarray(256, 320), want);
  assert.equal(place(1).menus![0].choices(v.doc).find(c => c.label.startsWith("Place 3:"))!.disabled, "empty");
  del(v, place(0));
  assert.ok(rost.subarray(0, 64).every(b => b === 0));
  assert.equal(place(0).actions![0].disabled!(v.doc), "the place is empty");
  // a character in a party is neither overwritten nor deleted (BOOT's terminate refuses it too)
  v.doc.edit(w => w.setByte("rost", 256 + 0x10, 0xff), "into the party");
  assert.match(place(4).actions![0].disabled!(v.doc)!, /in the party/);
  assert.ok(place(4).menus![0].choices(v.doc).every(c => /in the party/.test(c.disabled ?? "")));
  assert.match(place(0).menus![0].choices(v.doc).find(c => c.label.startsWith("Place 5:"))!.label, /as when it was formed/);
  while (v.doc.canUndo()) v.doc.undo();
  assert.deepEqual(encode(save), raw);
});
