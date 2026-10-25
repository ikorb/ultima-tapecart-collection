// Ultima VI's fields from the cheat menu's research: the name tables
// against the original disks, the condition bits, the level nibble, the BCD
// clock, the inventory's slots, and a played save of your own if present.

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { decode, encode } from "../src/container/ucsv.ts";
import { open } from "../src/container/open.ts";
import { D64 } from "../src/container/d64.ts";
import { view } from "../src/games/u6.ts";
import { OBJECTS, NPCS } from "../src/games/u6names.ts";
import { ORIGINAL_SAVE_AREA } from "../src/games/u6original.ts";
import { allFields } from "../src/games/model.ts";
import { NO_FIXTURES, COLLECTION, fixture, original } from "./fixtures.ts";


// a save from a played session, where a developer has one (not shipped)
const USER_SAVE = join(COLLECTION, "build", "user-saves", "ultima_vi_save.S00");

function field(v: ReturnType<typeof view>, id: string) {
  const f = allFields(v).find(x => x.field.id === id);
  assert.ok(f, id);
  return f.field;
}

const text = (b: Uint8Array) => [...b].map(c => c >= 1 && c <= 26 ? String.fromCharCode(c + 0x60) : String.fromCharCode(c)).join("");

test("the object names are 1A's table, the NPC names the conversations'", (t) => {
  const surface = original("u6-1a");
  if (!surface) return t.skip("no original Surface disk");
  const d = new D64(surface);
  const raw = [...Array(10).keys()].map(k => d.sector(35, k));
  const all = new Uint8Array(raw.reduce((n, r) => n + r.length, 0));
  raw.reduce((at, r) => (all.set(r, at), at + r.length), 0);
  OBJECTS.forEach((name, k) => {
    const e = all.subarray(16 * k, 16 * k + 16);
    const s = text(e.subarray(0, e.indexOf(0) < 0 ? 16 : e.indexOf(0)));
    // the singular: "/x\y" keeps x, "\y" drops y (each up to the next space)
    assert.equal(s.replace(/\/([^\\]*)\\\S*/g, "$1").replace(/\\\S*/g, ""), name, `object $${k.toString(16)}`);
  });
  const seen = new Map<number, string>();
  for (const disk of ["u6-2a", "u6-2b", "u6-3a"]) {
    const img = original(disk);
    if (!img) return t.skip(`no ${disk}`);
    const p = new D64(img);
    for (const e of p.files()) {
      const data = p.read(e);
      if (data[0] !== 0xff) continue;
      seen.set(data[1], text(data.subarray(2, data.indexOf(0xf1))));
    }
  }
  assert.equal(seen.size, 202);
  for (const [n, name] of seen) assert.equal(NPCS[n], name, `NPC ${n}`);
});

test("the played session reads as the game left it", { skip: NO_FIXTURES }, () => {
  const v = view(decode(fixture("u6.seq")));
  assert.equal(v.doc.value(field(v, "year")), 161);
  assert.equal(v.doc.value(field(v, "month")), 7);
  assert.equal(v.doc.value(field(v, "day")), 4);
  assert.equal(v.doc.value(field(v, "c0.level")), 3);
  for (const id of ["poisoned", "paralysed", "asleep", "protected", "invisible"])
    assert.equal(v.doc.value(field(v, `c0.${id}`)), false, id);
  assert.equal(v.doc.value(field(v, "c0.party")), true);
});

test("the level is the low nibble, the year BCD with its low digits first", { skip: NO_FIXTURES }, () => {
  const save = decode(fixture("u6.seq"));
  const v = view(save);
  const a = v.doc.area("save");
  a.set(0x57ba - 0x5400, 0xf3);                       // a high nibble the level must keep
  v.doc.set(field(v, "c0.level"), 5);
  assert.equal(a.get(0x57ba - 0x5400), 0xf5);
  assert.throws(() => v.doc.set(field(v, "c0.level"), 16));
  v.doc.set(field(v, "year"), 1234);
  assert.deepEqual([a.get(0x587e - 0x5400), a.get(0x587f - 0x5400)], [0x34, 0x12]);
  v.doc.set(field(v, "month"), 12);
  assert.equal(a.get(0x587d - 0x5400), 0x12);
  v.doc.set(field(v, "c0.poisoned"), true);
  assert.equal(a.get(0x5816 - 0x5400) & 0x08, 0x08);
  v.doc.undo();
  assert.equal(a.get(0x5816 - 0x5400) & 0x08, 0);
});

test("an inventory slot: filled with one, worn things readied, emptied to zeros; misplaced things warned of", { skip: NO_FIXTURES }, () => {
  const v = view(decode(fixture("u6.seq")));
  const a = v.doc.area("save");
  const at = (arr: number, p: number, k: number) => arr - 0x5400 + p * 32 + k;
  const empty = [...Array(24).keys()].find(k => a.get(at(0x54c0, 0, k)) === 0)!;
  v.doc.set(field(v, `inv0.${empty}.obj`), 0x60);     // gold coins
  assert.equal(a.get(at(0x5580, 0, empty)), 1);
  v.doc.set(field(v, `inv0.${empty}.qty`), 200);
  v.doc.set(field(v, `inv0.${empty}.obj`), 0);
  for (const arr of [0x5400, 0x54c0, 0x5580, 0x5640]) assert.equal(a.get(at(arr, 0, empty)), 0);
  for (let k = 24; k < 32; k++) v.doc.set(field(v, `inv0.${k}.obj`), 0);
  assert.deepEqual(v.warnings(), []);
  v.doc.set(field(v, "inv0.25.obj"), 0x12);           // a sword on the head
  assert.equal(a.get(at(0x5400, 0, 25)), 0x18);
  assert.match(v.warnings().map(w => w.text).join("\n"), /sword on the head: the Ready command puts it on the weapon hand/);
  v.doc.set(field(v, "inv0.25.obj"), 0);
  v.doc.set(field(v, "inv0.28.obj"), 0x13);           // two hands' worth in the shield hand
  v.doc.set(field(v, "inv0.27.obj"), 0x12);           // a sword in the weapon hand: fine
  v.doc.set(field(v, "inv0.30.obj"), 0x31);           // a second ring: fine
  assert.deepEqual(v.warnings().filter(w => !/two-handed/.test(w.text)), []);
  assert.equal(v.warnings().length, 1);
});

test("a played save (build/user-saves): the Avatar is poisoned, Lord British met, five spells known", (t) => {
  if (!existsSync(USER_SAVE)) return t.skip("no build/user-saves/ultima_vi_save.S00");
  const v = view(open(new Uint8Array(readFileSync(USER_SAVE)), "ultima_vi_save.S00").save);
  assert.equal(v.doc.value(field(v, "c0.poisoned")), true);
  assert.equal(v.doc.value(field(v, "c1.poisoned")), false);
  assert.equal(v.doc.value(field(v, "npc5.met")), true);
  assert.equal(v.doc.value(field(v, "inv0.0.obj")), OBJECTS.indexOf("Orb of the Moons"));
  assert.equal(v.doc.value(field(v, "inv0.27.obj")), OBJECTS.indexOf("sword"));
  const known = allFields(v).filter(f => f.field.id.startsWith("spell.") && v.doc.value(f.field)).map(f => f.field.label);
  assert.deepEqual(known, ["Dispel Magic", "Heal", "Help", "Light", "Poison"]);
  assert.equal(v.doc.value(field(v, "karma")), 35);
});

test("a sector the file lacks reads as the original disk's, and an edit there adds it", { skip: NO_FIXTURES }, () => {
  const surface = original("u6-1a");
  if (surface) {
    const d = new D64(surface);
    for (let k = 0; k < 12; k++) assert.deepEqual(ORIGINAL_SAVE_AREA.subarray(k * 256, k * 256 + 256), d.sector(6, 9 + k), `sector ${9 + k}`);
  }                                                   // (without the disk, the embedded sectors go unchecked)
  const raw = fixture("u6.seq");
  const save = decode(raw);
  const sectors = () => save.records.flatMap(r => r.kind === "sector" ? [r.sector] : []);
  assert.ok(!sectors().includes(14), "the played session has no sector 14");
  const v = view(save);
  const f = field(v, "spell.2.6");                    // Protection: $5995, in sector 14
  assert.equal(v.doc.value(f), (ORIGINAL_SAVE_AREA[0x5995 - 0x5400] & 0x40) !== 0);
  v.doc.set(f, true);
  assert.deepEqual(sectors(), [...sectors()].sort((a, b) => a - b));
  const s14 = save.records.find(r => r.kind === "sector" && r.sector === 14);
  assert.ok(s14 && s14.kind === "sector");
  const want = ORIGINAL_SAVE_AREA.slice(0x500, 0x600);
  want[0x95] |= 0x40;
  assert.deepEqual(s14.data, want);
  const again = view(decode(encode(save)));
  assert.equal(again.doc.value(field(again, "spell.2.6")), true);
  v.doc.undo();                                       // the sector the original's again: out of the file
  assert.ok(!sectors().includes(14));
  assert.deepEqual(encode(save), raw);
});
