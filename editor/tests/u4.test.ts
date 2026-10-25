// Ultima IV's fields against the seeded save (test_page.seed_u4: a played
// game, "AVATAR G HP 200/200") and C64UltimaEditor's played disk.

import { test } from "node:test";
import assert from "node:assert/strict";
import { decode, encode } from "../src/container/ucsv.ts";
import { open } from "../src/container/open.ts";
import { view } from "../src/games/u4.ts";
import { allFields, changes, beyondRules } from "../src/games/model.ts";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { NO_FIXTURES, COLLECTION, fixture, have } from "./fixtures.ts";

function field(v: ReturnType<typeof view>, id: string) {
  const f = allFields(v).find(x => x.field.id === id);
  assert.ok(f, id);
  return f.field;
}

test("the seeded game reads as the launcher page shows it", { skip: NO_FIXTURES }, () => {
  const v = view(decode(fixture("u4.seq")));
  assert.equal(v.doc.value(field(v, "p0.name")), "AVATAR");
  assert.equal(v.doc.value(field(v, "p0.status")), 0xc7);
  assert.equal(v.doc.value(field(v, "p0.hp")), 200);
  assert.equal(v.doc.value(field(v, "p0.maxhp")), 200);
  assert.equal(v.doc.value(field(v, "size")), 1);
  assert.deepEqual(v.warnings(), []);
  for (const { field: f } of allFields(v)) assert.ok(v.doc.has(f), f.id);
});

test("an edit changes exactly its bytes, and undo puts them back", { skip: NO_FIXTURES }, () => {
  const raw = fixture("u4.seq");
  const save = decode(raw);
  const v = view(save);
  v.doc.set(field(v, "p0.str"), 25);
  v.doc.set(field(v, "gold"), 9999);
  v.doc.set(field(v, "p0.class"), 7);               // shepherd: the mask byte follows
  const slot = save.slots[2] as Uint8Array, inv = save.slots[3] as Uint8Array;
  assert.equal(slot[0x13], 0x25);
  assert.equal(slot[0x11], 7);
  assert.equal(slot[0x17], 0x01);
  assert.deepEqual([...inv.subarray(0x13, 0x15)], [0x99, 0x99]);
  assert.deepEqual(changes(v).map(c => c.field.id).sort(), ["gold", "p0.class", "p0.str"]);
  const out = encode(save);
  const diff = [...out].map((b, k) => b !== raw[k] ? k : -1).filter(k => k >= 0);
  assert.ok(diff.length <= 4 + 2 + 2, `bytes changed: ${diff}`);   // 4 data bytes, the 2 check bytes
  while (v.doc.canUndo()) v.doc.undo();
  assert.deepEqual(encode(save), raw);
  while (v.doc.canRedo()) v.doc.redo();
  assert.equal(slot[0x11], 7);
  assert.equal(slot[0x13], 0x25);
});

test("values the bytes cannot hold are refused; the game's own limits are not enforced", { skip: NO_FIXTURES }, () => {
  const v = view(decode(fixture("u4.seq")));
  v.doc.set(field(v, "p0.str"), 99);                // a trainer's party: the game itself would stop at 50
  v.doc.set(field(v, "p0.maxhp"), 9999);
  assert.throws(() => v.doc.set(field(v, "p0.str"), 100), RangeError);
  assert.throws(() => v.doc.set(field(v, "gold"), 10000), RangeError);
  assert.throws(() => v.doc.set(field(v, "p0.name"), "A NAME FAR TOO LONG"), RangeError);
  v.doc.set(field(v, "p0.name"), "lord brit");
  assert.equal(v.doc.value(field(v, "p0.name")), "LORD BRIT");
});

test("C64UltimaEditor's played disk: eight named characters", { skip: !have("zoggins_u4.d64") && "no sample" }, () => {
  // the game's own disk, not a launcher file: read its blocks 271-275 into a save
  const img = fixture("zoggins_u4.d64");
  const blocks = [271, 272, 273, 274, 275].map(b => img.slice(b * 256, b * 256 + 256));
  const v = view({ game: 4, version: 1, slots: blocks, records: [] });
  const names = Array.from({ length: 8 }, (_, i) => v.doc.value(field(v, `p${i}.name`)));
  assert.ok(names.every(n => typeof n === "string" && n.length > 0), String(names));
  for (let i = 0; i < 8; i++) {
    const c = v.doc.value(field(v, `p${i}.class`)) as number;
    assert.equal(blocks[2][i * 32 + 0x17], 0x80 >> c, `the class mask of ${names[i]}`);
  }
  const o = open(img, "x.d64");                     // no launcher file on it: the game's own disk
  assert.equal(o.wrapper.kind, "gamedisk");
  assert.ok(o.notes.some(n => /would not take it/.test(n)), "a NUL-padded name: the launcher refuses it");
});

test("a trainer's party opens, every value beyond the game's limits flagged, nothing refused", () => {
  // a trainer-edited save from a played session, where a developer has one (not shipped)
  const path = join(COLLECTION, "build", "user-saves", "ultima_iv_save.S00");
  if (!existsSync(path)) return;
  const raw = new Uint8Array(readFileSync(path));
  const o = open(raw, "u4.S00");
  const v = view(o.save);
  const over = beyondRules(v);
  assert.ok(over.some(x => x.field.id === "p0.str" && x.value === 99), "strength 99 flagged");
  assert.ok(over.some(x => x.field.id === "p0.maxhp" && x.value === 9999), "max HP 9999 flagged");
  const str = field(v, "p0.str");
  v.doc.set(str, 98);                                // still editable as it is
  assert.ok(beyondRules(v).some(x => x.field.id === "p0.str"));
  v.doc.set(str, 50);
  assert.ok(!beyondRules(v).some(x => x.field.id === "p0.str"));
  const mx = field(v, "p0.maxhp");
  v.doc.set(mx, 750);                                // not a multiple of 100
  assert.ok(beyondRules(v).some(x => x.field.id === "p0.maxhp"));
});
