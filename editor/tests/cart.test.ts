// The cart itself (.tcrt): every game's save read off it as the page's own
// export reads it (make_fixtures.py's cart.tcrt, checked there against the
// page), edits written back into that game's place only, Ultima II's and
// VI's logs a new half each time, a journal a power cut left finished, and
// a cart of another layout refused.  tests/test_editor.py compares the
// written flash with the page's own import of the same edits, in py65.

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { open, serialise, gamesOnCart, OpenError, type Opened } from "../src/container/open.ts";
import * as ucsv from "../src/container/ucsv.ts";
import * as tcrt from "../src/container/tcrt.ts";
import { JOURNALS, SETTINGS, SET_LAYOUT, LAYOUT, U2_LOG, U6_LO, U6_MID, U6_HI } from "../src/container/cart.ts";
import { viewOf } from "../src/games/index.ts";
import { allFields } from "../src/games/model.ts";
import { COLLECTION, GAMES, have, fixture } from "./fixtures.ts";

const NO_CART = have("cart.tcrt") ? false : "no build/editor-fixtures/cart.tcrt (run make_fixtures.py)";
const FRESH = join(COLLECTION, "build", "ultima-collection.tcrt");

function flashOf(b: Uint8Array): Uint8Array { return tcrt.parse(b).flash; }

/** The cart with one field of one game set, written out. */
function edited(cart: Uint8Array, game: number, id: string, value: number | string): { out: Uint8Array; o: Opened } {
  const o = open(cart, "cart.tcrt", game);
  const v = viewOf(o.save);
  const f = allFields(v).find(x => x.field.id === id);
  assert.ok(f, `${id} in game ${game}`);
  v.doc.set(f.field, value);
  return { out: serialise(o), o };
}

/** The 4 KiB blocks in which two flashes differ. */
function blocks(a: Uint8Array, b: Uint8Array): number[] {
  const out: number[] = [];
  for (let at = 0; at < a.length; at += 0x1000)
    if (!a.subarray(at, at + 0x1000).every((v, i) => v === b[at + i])) out.push(at);
  return out;
}

const EDITS: [number, string, number | string][] = [
  [1, "p1.food", 999], [2, "hp", 1500], [3, "plrs1.hp", 275], [4, "gold", 9999], [5, "gold", 999], [6, "karma", 42],
];
// where each game's save may change the flash: its save region
const REGION: [number, number][] = [[0, 0], [0x1f8000, 0x1ff000], [0x1e4000, 0x1ec000], [0x1ec000, 0x1f8000],
                                    [0x1de000, 0x1e4000], [0x1d7000, 0x1de000], [0x197000, 0x1d7000]];

test("every game reads off the cart as the page exports it", { skip: NO_CART }, () => {
  const cart = fixture("cart.tcrt");
  GAMES.forEach((g, i) => {
    const o = open(cart, "cart.tcrt", i + 1);
    assert.deepEqual(ucsv.encode(o.save), fixture(`${g}.seq`), g);
    assert.equal(o.wrapper.kind, "tcrt");
  });
  assert.deepEqual(gamesOnCart(cart).map(g => g.status), ["4 characters", "", "", "", "", ""]);
});

test("a cart needs a game picked", { skip: NO_CART }, () => {
  assert.throws(() => open(fixture("cart.tcrt"), "cart.tcrt"), /pick one/);
  assert.throws(() => open(fixture("u4.seq"), "u4.seq", 4), /not a cart/);
});

test("a fresh cart: the games never saved say so", { skip: existsSync(FRESH) ? false : "no build/ultima-collection.tcrt" }, () => {
  const fresh = new Uint8Array(readFileSync(FRESH));
  assert.deepEqual(gamesOnCart(fresh).map(g => g.status),
    ["no characters", "never saved on this cart", "", "", "", "never saved on this cart"]);
  assert.deepEqual(open(fresh, "x", 6).save.records, []);
  // an edit of a never-saved Ultima VI starts its log with the sector it changes
  const { out } = edited(fresh, 6, "karma", 42);
  const again = open(out, "x", 6);
  assert.deepEqual(again.save.records.map(r => r.kind === "sector" ? r.sector : r.name), [13]);
});

test("nothing edited, nothing changed", { skip: NO_CART }, () => {
  const cart = fixture("cart.tcrt");
  for (let g = 1; g <= 6; g++) assert.deepEqual(serialise(open(cart, "cart.tcrt", g)), cart, `game ${g}`);
});

test("an edit changes only its game's save region, and reads back", { skip: NO_CART }, () => {
  const cart = fixture("cart.tcrt");
  for (const [game, id, value] of EDITS) {
    const { out } = edited(cart, game, id, value);
    assert.deepEqual(out.subarray(0, tcrt.HEADER - 4), cart.subarray(0, tcrt.HEADER - 4), "the header kept");
    const changed = blocks(flashOf(cart), flashOf(out));
    assert.ok(changed.length > 0, `game ${game}`);
    const [lo, hi] = REGION[game];
    assert.ok(changed.every(a => a >= lo && a < hi), `game ${game}: ${changed.map(a => a.toString(16))}`);
    const v = viewOf(open(out, "cart.tcrt", game).save);
    assert.equal(v.doc.value(allFields(v).find(x => x.field.id === id)!.field), value, `game ${game}`);
    if (game === 1 || game === 4) assert.equal(changed.length, 1, "one slot");
    // every other game reads as it did
    for (let g = 1; g <= 6; g++) if (g !== game)
      assert.deepEqual(ucsv.encode(open(out, "x", g).save), ucsv.encode(open(cart, "x", g).save), `${game} -> ${g}`);
  }
});

test("Ultima II's and VI's logs: a new half each time, the generation one more", { skip: NO_CART }, () => {
  let cart = fixture("cart.tcrt");
  const u2gen = (f: Uint8Array) => [0, 1].map(h => {
    const d = U2_LOG + h * 0x4000 + 63 * 256;
    return (f[d + 0xfe] ^ 0xff) === f[d + 0xff] ? f[d + 0xfe] : null;
  });
  const u6gen = (f: Uint8Array) => [U6_MID, U6_HI].map(top => {
    const e = f.subarray(top - 20, top);
    return e[0] === 0xff ? null : e[0] === 0xfe ? e[12] | e[13] << 8 : 0;
  });
  // the seed's log is in half 1, generation 7; the imported session's in half 0
  assert.deepEqual(u2gen(flashOf(cart)), [null, 7]);
  assert.deepEqual(u6gen(flashOf(cart)), [0, null]);
  for (let k = 1; k <= 3; k++) {
    cart = edited(cart, 2, "hp", 1000 + k).out;
    cart = edited(cart, 6, "karma", 40 + k).out;
    const f = flashOf(cart);
    assert.deepEqual(u2gen(f), k & 1 ? [7 + k, null] : [null, 7 + k], `U2 save ${k}: the old half's directory erased`);
    assert.deepEqual(u6gen(f), k & 1 ? [null, k] : [k, null], `U6 save ${k}`);
    const old = k & 1 ? [U6_LO, U6_MID] : [U6_MID, U6_HI];
    assert.ok(f.subarray(old[0], old[1]).every(b => b === 0xff), "U6's old half erased");
  }
  const v2 = viewOf(open(cart, "x", 2).save);
  assert.equal(v2.doc.value(allFields(v2).find(x => x.field.id === "hp")!.field), 1003);
  const v6 = viewOf(open(cart, "x", 6).save);
  assert.equal(v6.doc.value(allFields(v6).find(x => x.field.id === "karma")!.field), 43);
  // the chunk files went across with the save area
  assert.deepEqual(ucsv.encode(open(cart, "x", 6).save).length, fixture("u6.seq").length);
});

test("a journal a power cut left is finished, as the first stage does", { skip: NO_CART }, () => {
  const t = tcrt.parse(fixture("cart.tcrt"));
  const u4 = JOURNALS.find(j => j.game === 4)!;
  const slot = 0x1de000;                                  // U4's first slot, block 271 (gold is in 273)
  const page = new Uint8Array(256).map((_, i) => i ^ 0x5a);
  const f = t.flash.slice();
  f.set(page, u4.at + 256);                               // the slot's page 0, in the journal's page 1
  f.set([0x4a, 0x4e, slot >> 8 & 255, slot >> 16], u4.at);
  const cart = tcrt.pack(t, f);
  const o = open(cart, "cart.tcrt", 4);
  assert.deepEqual(o.save.slots[0], page);
  assert.ok(o.notes.some(n => /Ultima IV that a power cut/.test(n)), o.notes.join());
  // written back: the slot holds it, the journal is erased
  const out = flashOf(edited(cart, 4, "gold", 1234).out);
  assert.deepEqual(out.subarray(slot, slot + 256), page);
  assert.ok(out.subarray(u4.at, u4.at + 0x1000).every(b => b === 0xff));
  // a header begun and not whole names nothing: the journal goes, the slot stays
  const g = t.flash.slice();
  g.set(page, u4.at + 256);
  g.set([0x4a, 0x4e, 0xff, 0xff], u4.at);
  const o2 = open(tcrt.pack(t, g), "x", 4);
  assert.deepEqual(o2.save.slots[0], open(fixture("cart.tcrt"), "x", 4).save.slots[0]);
  assert.ok(!o2.notes.some(n => /power cut/.test(n)));
});

test("a cart of another save layout, or none, is refused", { skip: NO_CART }, () => {
  const t = tcrt.parse(fixture("cart.tcrt"));
  const f = t.flash.slice();
  f[SETTINGS + SET_LAYOUT] = LAYOUT + 1;
  assert.throws(() => gamesOnCart(tcrt.pack(t, f)), /layout 2/);
  f.fill(0xff, SETTINGS, SETTINGS + 0x1000);
  assert.throws(() => open(tcrt.pack(t, f), "x", 1), /no layout stamp/);
  const g = t.flash.slice();
  g.fill(0xff, 0, 0x8000);                                // no launcher
  assert.throws(() => open(tcrt.pack(t, g), "x", 1), OpenError);
  assert.throws(() => open(fixture("cart.tcrt").slice(0, 5000), "x", 1), /cut short/);
});

test("the layout is the build's (regions.py, the page's symbols)", { skip: have("layout.json") ? false : "no layout.json" }, () => {
  const want = JSON.parse(readFileSync(join(COLLECTION, "build", "editor-fixtures", "layout.json"), "utf8"));
  assert.equal(LAYOUT, want.layout);
  assert.equal(SETTINGS, want.settings);
  assert.equal(SET_LAYOUT, want.set_layout);
  assert.equal(U2_LOG, want.u2_log);
  assert.deepEqual([U6_LO, U6_MID, U6_HI], want.u6);
  assert.deepEqual(Object.fromEntries(JOURNALS.map(j => [String(j.game), [j.lo, j.at, j.blocks * 0x1000]])), want.journals);
});
