// The games' own disks: recognised, their saves read where the games keep
// them, written back with only those places changed -- on the originals,
// played disks and C64UltimaEditor's.  The table matches the build's.

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { DISKS, recognise } from "../src/container/gamedisks.ts";
import { D64 } from "../src/container/d64.ts";
import { open, serialise } from "../src/container/open.ts";
import { viewOf } from "../src/games/index.ts";
import { allFields } from "../src/games/model.ts";
import { COLLECTION, original, have, fixture } from "./fixtures.ts";

const ORIGINALS: [string, number, string][] = [     // path, game, the disk's label
  ["u1", 1, "Ultima I"],
  ["u2b", 2, "Player"],
  ["u3b", 3, "Scenario"],
  ["u4c", 4, "Britannia"],
  ["u5-2a", 5, "Britannia (2A)"],
  ["u5-2b", 5, "Underworld (2B)"],
  ["u6-1a", 6, "Surface (1A)"],
];

test("each game's disk is recognised as the original, and the others are not", () => {
  for (const [path, game, label] of ORIGINALS) {
    const img = original(path);
    if (!img) continue;
    const r = recognise(img);
    assert.ok(r, path);
    assert.equal(r.disk.game, game);
    assert.equal(r.disk.label, label);
    assert.ok(r.original, path);
  }
  for (const path of ["u4b", "u5-1a",
                      "u6-3b", "u2a"]) {
    const img = original(path);
    if (img) assert.equal(recognise(img), null, path);
  }
});

test("a game's disk opens; unchanged, it writes back as it was; an edit changes only its own place", () => {
  const edits: Record<number, [string, number | string]> = {
    1: ["p1.food", 777], 2: ["hp", 1234], 3: ["plrs0.gold", 321], 4: ["p0.str", 33], 5: ["gold", 4321], 6: ["c0.str", 28],
  };
  for (const [path, game] of ORIGINALS) {
    const img = original(path);
    if (!img) continue;
    const o = open(img, path);
    assert.equal(o.wrapper.kind, "gamedisk");
    assert.deepEqual(serialise(o), img, `${path}: unchanged`);
    const v = viewOf(o.save);
    const [id, val] = edits[game];
    const f = allFields(v).find(x => x.field.id === id)?.field;
    assert.ok(f, id);
    if (!v.doc.has(f)) continue;                      // (U1's original has its characters scratched)
    v.doc.set(f, val);
    const out = serialise(o);
    const diffSectors = new Set<number>();
    for (let k = 0; k < img.length; k++) if (out[k] !== img[k]) diffSectors.add(k >> 8);
    assert.ok(diffSectors.size >= 1 && diffSectors.size <= 1, `${path}: ${diffSectors.size} sectors changed`);
    const back = viewOf(open(out, path).save);
    assert.equal(back.doc.value(f), val, `${path}: read back`);
  }
});

test("a file slot keeps its load address and chain", () => {
  const img = original("u5-2a");
  if (!img) return;
  const o = open(img, "2A");
  const v = viewOf(o.save);
  v.doc.set(allFields(v).find(x => x.field.id === "c0.str")!.field, 25);
  const before = new D64(img), after = new D64(serialise(o));
  const name = Uint8Array.from([..."ROSTER"].map(c => c.charCodeAt(0)));
  const e0 = before.find(name)!, e1 = after.find(name)!;
  assert.deepEqual(after.chain(e1), before.chain(e0));
  const data = after.read(e1);
  assert.equal(data[0] | data[1] << 8, 0x1000);
  assert.equal(data[2 + 0x84], 0x25);
});

test("other editions' disks open; one the launcher would refuse says so", () => {
  // C64UltimaEditor's: U2's Sierra name and U3's 1984 one, which the launcher
  // takes; its U4 disk has a NUL-padded name and no disk number, which it does not
  for (const [g, refused] of [["u2", false], ["u3", false], ["u4", true]] as [string, boolean][]) {
    if (!have(`zoggins_${g}.d64`)) continue;
    const o = open(fixture(`zoggins_${g}.d64`), g);
    assert.equal(o.wrapper.kind, "gamedisk", g);
    assert.equal(o.notes.some(n => /would not take it/.test(n)), refused, g);
    assert.deepEqual(serialise(o), fixture(`zoggins_${g}.d64`));
  }
});

test("Ultima V's Britannia is not taken for Ultima IV's 1986 one of the same name", () => {
  const img = original("u5-2a");
  if (!img) return;
  const r = recognise(img);
  assert.ok(r);
  assert.equal(r.disk.game, 5);
  assert.ok(r.original);
});

test("the table is the build's (build/xfer.json)", () => {
  const p = join(COLLECTION, "build", "xfer.json");
  if (!existsSync(p)) return;
  const x = JSON.parse(readFileSync(p, "utf8")) as Record<string, { label: string; bam_name: string; alt_name: string | null; id: string;
    check_id: boolean; check: number[] | null; slots: { name?: string; load?: number; lo?: number; hi?: number;
    optional?: boolean; sectors?: [number, number][] }[] }[]>;
  for (const [g, disks] of Object.entries(x)) {
    const game = Number(g.slice(1));
    for (const xd of disks) {
      const mine = DISKS.find(d => d.game === game && d.label === xd.label);
      if (game === 6) { if (xd.label.startsWith("Surface")) assert.ok(mine); continue; }
      assert.ok(mine, `${g} ${xd.label}`);
      const bam = Uint8Array.from(xd.bam_name.match(/../g)!.map(h => parseInt(h, 16)));
      let n = bam.length;
      while (n && bam[n - 1] === 0xa0) n--;
      assert.equal(mine.names[0], String.fromCharCode(...bam.subarray(0, n)), `${g} ${xd.label}: the name`);
      const alt = xd.alt_name ? Uint8Array.from(xd.alt_name.match(/../g)!.map(h => parseInt(h, 16))) : null;
      let m = alt ? alt.length : 0;
      while (alt && m && alt[m - 1] === 0xa0) m--;
      assert.deepEqual(mine.names.slice(1), alt ? [String.fromCharCode(...alt.subarray(0, m))] : [],
                       `${g} ${xd.label}: the other edition's name`);
      assert.deepEqual(mine.check, xd.check, `${g}: the check`);
      assert.equal(mine.slots.length, xd.slots.length);
      xd.slots.forEach((s, k) => {
        const m = mine.slots[k];
        if (s.sectors) assert.deepEqual(m.kind === "raw" ? m.sectors : null, s.sectors, `${g} slot ${k}`);
        else {
          assert.ok(m.kind === "file", `${g} slot ${k}`);
          assert.deepEqual([m.name, m.load, m.lo, m.hi], [s.name, s.load, s.lo, s.hi], `${g} slot ${k}`);
        }
      });
    }
  }
});
