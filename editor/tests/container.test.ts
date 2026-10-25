// The containers: the save file, PC64, .d64 -- against the files the
// launcher's page itself writes (make_fixtures.py).

import { test } from "node:test";
import assert from "node:assert/strict";
import * as ucsv from "../src/container/ucsv.ts";
import * as pc64 from "../src/container/pc64.ts";
import { D64, blankD64, petscii, same } from "../src/container/d64.ts";
import { open, serialise, savesOnDisk, OpenError } from "../src/container/open.ts";
import { GAMES, NO_FIXTURES, fixture } from "./fixtures.ts";

const SLOTS = [5, 12, 5, 5, 6];       // docs/save-format.md's tables

test("every game's file decodes and encodes byte for byte", { skip: NO_FIXTURES }, () => {
  GAMES.forEach((g, i) => {
    const raw = fixture(`${g}.seq`);
    const u = ucsv.decode(raw);
    assert.equal(u.game, i + 1);
    if (u.game !== 6) assert.equal(u.slots.length, SLOTS[i], g);
    else assert.equal(u.records.length, 12, "tests/test_u6_xfer.py's played disks: 2 sectors, 10 files");
    assert.deepEqual(ucsv.encode(u), raw, g);
  });
});

test("the slots are as the format says", { skip: NO_FIXTURES }, () => {
  const u1 = ucsv.decode(fixture("u1.seq"));
  assert.equal(u1.slots[0]?.length, 64);
  assert.equal(u1.slots[1], null, "Anselm has no character file");
  assert.equal(u1.slots[2]?.length, 458);
  const u3 = ucsv.decode(fixture("u3.seq"));
  assert.deepEqual(u3.slots.map(s => s?.length), [4096, 256, 1280, 256, 256]);
  const u4 = ucsv.decode(fixture("u4.seq"));
  assert.deepEqual(u4.slots.map(s => s?.length), [256, 256, 256, 256, 256]);
  const u6 = ucsv.decode(fixture("u6.seq"));
  const secs = u6.records.filter(r => r.kind === "sector").map(r => r.kind === "sector" ? r.sector : 0);
  // only what differs from the original disks: the played disks' party, sectors 12 and 13
  assert.deepEqual(secs, [12, 13]);
});

test("a damaged file is refused", { skip: NO_FIXTURES }, () => {
  const good = fixture("u3.seq");
  for (const at of [0, 4, 5, 6, 100, good.length - 3, good.length - 1]) {
    const bad = good.slice();
    bad[at] ^= 0x10;
    assert.throws(() => ucsv.decode(bad), ucsv.UcsvError, `byte ${at}`);
  }
  assert.throws(() => ucsv.decode(good.slice(0, good.length - 1)), ucsv.UcsvError);
  const longer = new Uint8Array(good.length + 1);
  longer.set(good);
  assert.throws(() => ucsv.decode(longer), ucsv.UcsvError, "a byte too many");
  // a short body with valid check bytes: cut short, not damaged
  const cut = good.slice(0, 40);
  const [s1, s2] = ucsv.checkBytes(cut);
  assert.throws(() => ucsv.decode(Uint8Array.from([...cut, s1, s2])), /cut short/);
});

test("PC64: the header, and the file inside", { skip: NO_FIXTURES }, () => {
  for (const g of GAMES) {
    const s00 = fixture(`${g}.s00`), seq = fixture(`${g}.seq`);
    assert.ok(pc64.isPc64(s00));
    const p = pc64.unwrap(s00);
    assert.deepEqual(p.data, seq);
    assert.equal(String.fromCharCode(...p.name), ucsv.NAMES[GAMES.indexOf(g) + 1]);
    assert.deepEqual(pc64.wrap(p.name, p.data), s00);
  }
  assert.equal(pc64.typeOfName("ULTIMA IV SAVE.S00"), "S");
  assert.equal(pc64.typeOfName("x.p01"), "P");
});

test("each wrapper opens, and an unchanged save writes back the same file", { skip: NO_FIXTURES }, () => {
  for (const g of GAMES)
    for (const ext of ["seq", "s00", "d64"]) {
      const raw = fixture(`${g}.${ext}`);
      const o = open(raw, `${g}.${ext}`);
      assert.equal(o.wrapper.kind, ext === "seq" ? "plain" : ext === "s00" ? "pc64" : "d64");
      assert.deepEqual(serialise(o), raw, `${g}.${ext}`);
    }
});

test("an edit on a .d64 changes only the file's own sectors", { skip: NO_FIXTURES }, () => {
  const raw = fixture("u4.d64");
  const o = open(raw, "u4.d64");
  const slot = o.save.slots[2] as Uint8Array;
  slot[0x13] = 0x25;                                    // the Avatar's strength
  const out = serialise(o);
  const before = new D64(raw), after = new D64(out);
  const e = after.find(petscii("ULTIMA IV SAVE"));
  assert.ok(e);
  const mine = new Set(after.chain(e).map(([t, s]) => after.offset(t, s)));
  for (let o2 = 0; o2 < raw.length; o2 += 256)
    if (!mine.has(o2)) assert.deepEqual(out.subarray(o2, o2 + 256), raw.subarray(o2, o2 + 256), `sector at ${o2}`);
  const back = ucsv.decode(after.read(e));
  assert.equal(back.slots[2]?.[0x13], 0x25);
  assert.deepEqual(before.diskName(), after.diskName());
});

test("a .d64 with several save files needs a pick", { skip: NO_FIXTURES }, () => {
  const d = new D64(blankD64("SAVES"));
  d.create(petscii("ULTIMA IV SAVE"), fixture("u4.seq"));
  d.create(petscii("ULTIMA V SAVE"), fixture("u5.seq"));
  d.create(petscii("NOTES"), petscii("HELLO"));
  const saves = savesOnDisk(d.data);
  assert.deepEqual(saves.map(s => [s.name, s.game, s.type]), [["ULTIMA IV SAVE", 4, "SEQ"], ["ULTIMA V SAVE", 5, "SEQ"]]);
  assert.throws(() => open(d.data, "x.d64"), OpenError);
  const o = open(d.data, "x.d64", saves[1].raw);
  assert.equal(o.save.game, 5);
  assert.deepEqual(serialise(o), d.data);
});

test("a file that grows gets a new chain and a consistent BAM", () => {
  const d = new D64(blankD64("T"));
  d.create(petscii("A"), new Uint8Array(300).fill(1));
  const freeBefore = countFree(d);
  const e = d.find(petscii("A"));
  assert.ok(e);
  d.rewrite(e, new Uint8Array(1000).fill(2));
  const e2 = d.find(petscii("A"));
  assert.ok(e2);
  assert.equal(e2.blocks, 4);
  assert.deepEqual(d.read(e2), new Uint8Array(1000).fill(2));
  assert.equal(countFree(d), freeBefore - 2);
  for (const [t, s] of d.chain(e2)) assert.ok(!d.isFree(t, s));
  assert.ok(same(d.diskName(), petscii("T")));
});

function countFree(d: D64): number {
  let n = 0;
  const bam = d.sector(18, 0);
  for (let t = 1; t <= 35; t++) if (t !== 18) n += bam[4 * t];
  return n;
}
