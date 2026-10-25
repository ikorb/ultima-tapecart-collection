// The saves inside the cart's flash, as the launcher's page reads them for
// its file export and writes them for its file import (asm/page_file.s,
// page_xfer.s, page_u2l.s, page_u6x.s): an edited save goes onto the cart
// exactly as the page's I, F would put the same file there.
//
// Where each slot is comes from the cart itself -- the page's export tables
// at the end of the launcher's PRG (launcher.py XDATA, xfer.py's format) --
// since Ultima II's seeds move with the game data from build to build.  The
// rest is fixed by the save layout, which the settings page's stamp names
// (regions.py LAYOUT): the journals of U1, U3, U4 and U5 (docs/developer/saves.md),
// Ultima II's write log (u2log.py) and Ultima VI's (u6log.py).

import { DISKS, type Slot } from "./gamedisks.ts";
import type { Ucsv, U6Record } from "./ucsv.ts";

export const LAYOUT = 1;                 // regions.LAYOUT this editor knows
export const SETTINGS = 0x1ff000, SET_LAYOUT = 0x0c;
const LAUNCHER_LOC = 0x0000f8;
const BLOCK = 0x1000, PAGE = 0x100;
const NONE = 0, BYTES = 1, BLOCKS = 2, LOG = 0x80;

// regions.journal(): a game's journal at the top of its save region
export const JOURNALS = [
  { game: 1, lo: 0x1f8000, at: 0x1fe000, blocks: 1 },
  { game: 3, lo: 0x1ec000, at: 0x1f6000, blocks: 2 },
  { game: 4, lo: 0x1de000, at: 0x1e3000, blocks: 1 },
  { game: 5, lo: 0x1d7000, at: 0x1dd000, blocks: 1 },
];
export const U2_LOG = 0x1e4000, U2_PAGES = 64, U2_DATA = 63;
export const U6_LO = 0x197000, U6_MID = 0x1b7000, U6_HI = 0x1d7000;
const U6_BASES = [U6_LO, U6_MID], U6_TOPS = [U6_MID, U6_HI];
const KEYLEN = 12, ENTRY = 20, MAXSEC = 20, F6_LINKS = 0x02;
// the chunk files in the disks' directory order, as the page's export goes
const U6_FILES = [..."ABCDEFGH"].flatMap(a => [..."ABCDEFGH"].map(b => `S${a}${b}`))
  .concat([..."ABCDE"].flatMap(a => [..."ABCD"].map(b => `D${a}${b}`)));

export class CartError extends Error {}

export interface CartSlot { base: number; hdr: number; slot: Slot }

/** The flash, as the cart's commands change it: an erase sets a 4 KiB block
 *  to $FF, a write can only clear bits (a write that needs one set is a bug
 *  here, as it would be on the cart). */
class Flash {
  readonly b: Uint8Array;
  constructor(b: Uint8Array) { this.b = b; }
  erase(a: number): void { const s = a & ~(BLOCK - 1); this.b.fill(0xff, s, s + BLOCK); }
  write(a: number, d: ArrayLike<number>): void {
    for (let i = 0; i < d.length; i++) {
      if ((this.b[a + i] & d[i]) !== d[i]) throw new Error(`a write to unerased flash at $${(a + i).toString(16)}`);
      this.b[a + i] &= d[i];
    }
  }
  read(a: number, n: number): Uint8Array { return this.b.slice(a, a + n); }
  erased(a: number, n: number): boolean { return this.b.subarray(a, a + n).every(v => v === 0xff); }
}

// -- the cart as a whole -----------------------------------------------------------

export interface Prepared { flash: Uint8Array; notes: string[]; tables: Map<number, CartSlot[]> }

/** The cart's flash made ready to read: the layout checked, and a journal a
 *  power cut left finished, as the first stage (asm/boot.s) would at the next
 *  power-on.  The flash is not changed; the result is a copy. */
export function prepare(image: Uint8Array): Prepared {
  const f = new Flash(image.slice());
  const set = f.b.subarray(SETTINGS, SETTINGS + 16);
  if (!(set[0] === 0x55 && set[1] === 0x43 && set[2] === 0x46 && set[3] === 0x47) || set[SET_LAYOUT] !== LAYOUT) {
    const has = set[0] === 0x55 && set[1] === 0x43 && set[2] === 0x46 && set[3] === 0x47 ? set[SET_LAYOUT] : 0;
    throw new CartError(has
      ? `this cart's saves are laid out for another build of the collection (layout ${has}; this editor knows ${LAYOUT})`
      : "this cart has no layout stamp: it is not the Ultima Tapecart Collection, or a build from before the stamp");
  }
  const tables = exportTables(f.b);
  const notes: string[] = [];
  for (const j of JOURNALS) if (finishJournal(f, j))
    notes.push(`A save of ${TITLE[j.game]} that a power cut interrupted has been finished, as the cart does at its next power-on.`);
  return { flash: f.b, notes, tables };
}

const TITLE = ["", "Ultima I", "Ultima II", "Ultima III", "Ultima IV", "Ultima V", "Ultima VI"];

/** boot.s jn_one: true if a whole journal was copied into its slot. */
function finishJournal(f: Flash, j: typeof JOURNALS[number]): boolean {
  const h = f.read(j.at, 4);
  if ((h[0] & h[1]) === 0xff) return false;            // no header begun
  let done = false;
  const slot = h[3] << 16 | h[2] << 8;
  if (h[0] === 0x4a && h[1] === 0x4e && (h[2] & 0x0f) === 0 && slot >= j.lo && slot < j.at) {
    for (let k = 0; k < j.blocks; k++) f.erase(slot + k * BLOCK);
    for (let p = 1; p < j.blocks * 16; p++) {
      const a = j.at + p * PAGE;
      if (!f.erased(a, PAGE)) f.write(slot + (p - 1) * PAGE, f.read(a, PAGE));
    }
    done = true;
  }
  f.erase(j.at);
  return done;
}

/** The page's export tables (xfer.py table()), found by each game disk's
 *  BAM name in the launcher's PRG and checked against what this editor
 *  knows of the slots (gamedisks.ts). */
function exportTables(flash: Uint8Array): Map<number, CartSlot[]> {
  const at = flash[LAUNCHER_LOC] | flash[LAUNCHER_LOC + 1] << 8 | flash[LAUNCHER_LOC + 2] << 16;
  const len = flash[LAUNCHER_LOC + 3] | flash[LAUNCHER_LOC + 4] << 8;
  const prg = flash.subarray(at, at + len);
  const tail = prg.subarray(prg.length - 4);
  if (len < 64 || at + len > flash.length || ![0x55, 0x43, 0x53, 0x56].every((m, i) => tail[i] === m))
    throw new CartError("the cart's launcher has no export tables: it is not the Ultima Tapecart Collection, or not all of it");
  const out = new Map<number, CartSlot[]>();
  const bad = (what: string) => new CartError(`the cart's export table for ${what} is not as this editor knows it`);
  for (const disk of DISKS) {
    if (disk.game === 6) continue;
    const name = new Uint8Array(16).fill(0xa0);
    for (let i = 0; i < disk.names[0].length; i++) name[i] = disk.names[0].charCodeAt(i);
    let p = -1;
    for (let i = 1; i + 40 <= prg.length && p < 0; i++)
      if (prg[i - 1] === 0 && name.every((c, k) => prg[i + k] === c)) p = i;
    if (p < 0) throw bad(`${TITLE[disk.game]}'s ${disk.label} disk`);
    let i = p + 39;                 // name, other edition's name, ID flag, ID, check (4)
    const n = prg[i++];
    if (n !== disk.slots.length) throw bad(`${TITLE[disk.game]}'s ${disk.label} disk`);
    const slots = out.get(disk.game) ?? [];
    for (const want of disk.slots) {
      const kind = prg[i], base = prg[i + 1] | prg[i + 2] << 8 | prg[i + 3] << 16, hdr = prg[i + 4];
      i += 5;
      if (kind === 1 && want.kind === "raw") {
        const sectors: [number, number][] = [];
        const m = prg[i++];
        for (let k = 0; k < m; k++, i += 2) sectors.push([prg[i], prg[i + 1]]);
        if (sectors.join() !== want.sectors.join()) throw bad(`${TITLE[disk.game]}'s ${disk.label} disk`);
        slots.push({ base, hdr, slot: want });
      } else if (kind === 2 && want.kind === "file") {
        let fname = "";
        while (prg[i] !== 0 && i < prg.length) fname += String.fromCharCode(prg[i++]);
        i++;
        const w = (k: number) => prg[i + k] | prg[i + k + 1] << 8;
        if (fname !== want.name || w(0) !== want.load || w(2) !== want.lo || w(4) !== want.hi)
          throw bad(`${TITLE[disk.game]}'s ${disk.label} disk`);
        i += 7;
        slots.push({ base, hdr, slot: want });
      } else throw bad(`${TITLE[disk.game]}'s ${disk.label} disk`);
      if (disk.game === 2 ? !(hdr & LOG) : hdr & LOG || hdr > BLOCKS) throw bad(TITLE[disk.game]);
    }
    out.set(disk.game, slots);
  }
  return out;
}

/** What the page would say on a game's line in a pick: "" if nothing to tell. */
export function status(p: Prepared, game: number): string {
  const f = new Flash(p.flash);
  if (game === 2) return u2Active(f) ? "" : "never saved on this cart";
  if (game === 6) return u6Log(f) ? "" : "never saved on this cart";
  if (game === 1) {
    const ro = p.tables.get(1)![0].base;
    if (f.b[ro] !== 0xa5 || f.b[ro + 1] !== 0x5a) return "no characters";
    const n = [0, 1, 2, 3].filter(k => f.b[ro + PAGE + 16 * k] === 0xff).length;
    return n ? `${n} character${n > 1 ? "s" : ""}` : "no characters";
  }
  return "";
}

// -- reading: the page's file export (f_out, f6_out) ------------------------------

export function readCart(p: Prepared, game: number): Ucsv {
  const f = new Flash(p.flash);
  if (game === 6) return { game, version: 1, slots: [], records: u6Records(f) };
  const slots = p.tables.get(game)!.map(cs => readSlot(f, cs));
  return { game, version: 1, slots, records: [] };
}

function readSlot(f: Flash, cs: CartSlot): Uint8Array | null {
  const s = cs.slot;
  const pages = s.kind === "raw" ? s.sectors.length : 0;
  let at = cs.base, len: number;
  if (cs.hdr & LOG) {
    at = u2Find(f, cs.hdr & 0x7f) ?? cs.base;
    len = s.kind === "raw" ? pages * PAGE : s.hi;
  } else if (cs.hdr === NONE) {
    len = s.kind === "raw" ? pages * PAGE : s.hi;
  } else {
    const h = f.read(cs.base, 4);
    if (h[0] !== 0xa5 || h[1] !== 0x5a) return null;
    len = s.kind === "raw" ? pages * PAGE : cs.hdr === BLOCKS ? h[2] * PAGE : h[2] | h[3] << 8;
    at = cs.base + PAGE;
  }
  if (s.kind === "file" && (len < s.lo || len > s.hi))
    throw new CartError(`the cart's ${s.name} is ${len} bytes long, the game's is ${s.lo === s.hi ? s.lo : `${s.lo}-${s.hi}`}`);
  return f.read(at, len);
}

// -- writing: the page's file import (xi_write, f6_in) ----------------------------

/** The flash with `save` on it where it differs from `before` (what was read):
 *  Ultima I, III, IV and V slot by slot, Ultima II's and VI's logs as a new
 *  half holding the whole save, as the page's import does. */
export function writeCart(p: Prepared, save: Ucsv, before: Ucsv): Uint8Array {
  const f = new Flash(p.flash.slice());
  if (save.game === 6) {
    if (!sameRecords(save.records, before.records)) u6Write(f, save.records);
    return f.b;
  }
  const table = p.tables.get(save.game)!;
  if (save.slots.length !== table.length) throw new CartError(`${TITLE[save.game]} has ${table.length} slots, the save ${save.slots.length}`);
  const changed = table.map((_, k) => !sameBytes(save.slots[k], before.slots[k]));
  if (!changed.some(Boolean)) return f.b;
  if (save.game === 2) { u2Write(f, table, save.slots); return f.b; }
  table.forEach((cs, k) => { if (changed[k]) writeSlot(f, cs, save.slots[k]); });
  return f.b;
}

function sameBytes(a: Uint8Array | null, b: Uint8Array | null): boolean {
  if (!a || !b) return a === b;
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function sameRecords(a: U6Record[], b: U6Record[]): boolean {
  return a.length === b.length && a.every((r, i) => {
    const q = b[i];
    if (r.kind === "sector") return q.kind === "sector" && q.sector === r.sector && sameBytes(r.data, q.data);
    return q.kind === "file" && q.name === r.name && q.pages.length === r.pages.length
      && r.pages.every((pg, k) => sameBytes(pg, q.pages[k]));
  });
}

/** im_write: the slot's blocks erased, the data, the header last. */
function writeSlot(f: Flash, cs: CartSlot, data: Uint8Array | null): void {
  const s = cs.slot, len = data?.length ?? 0;
  if (data) {
    const ok = s.kind === "raw" ? len === s.sectors.length * PAGE : len >= s.lo && len <= s.hi;
    if (!ok) throw new CartError(`${s.kind === "file" ? s.name : "a slot"}: ${len} bytes do not fit it`);
  }
  const pages = (len >> 8) + (len & 255 ? 1 : 0) + (cs.hdr ? 1 : 0);
  const blocks = Math.max(1, (pages + 15) >> 4);
  for (let k = 0; k < blocks; k++) f.erase(cs.base + k * BLOCK);
  if (!data) return;                                      // an empty slot stays erased
  f.write(cs.base + (cs.hdr ? PAGE : 0), data);
  if (cs.hdr === BYTES) f.write(cs.base, [0xa5, 0x5a, len & 255, len >> 8]);
  else if (cs.hdr === BLOCKS) f.write(cs.base, [0xa5, 0x5a, len >> 8, 0]);
}

// -- Ultima II's write log (page_u2l.s, u2log.py) ---------------------------------

function u2Dir(f: Flash, half: number): Uint8Array {
  return f.read(U2_LOG + half * U2_PAGES * PAGE + U2_DATA * PAGE, PAGE);
}

/** lg_active: the half in use and its generation, or null for an empty log. */
function u2Active(f: Flash): { half: number; gen: number } | null {
  const d = [u2Dir(f, 0), u2Dir(f, 1)];
  const valid = d.map(x => (x[0xfe] ^ 0xff) === x[0xff]);
  if (valid[1] && (!valid[0] || ((d[0][0xfe] + 1) & 255) === d[1][0xfe])) return { half: 1, gen: d[1][0xfe] };
  if (valid[0]) return { half: 0, gen: d[0][0xfe] };
  return null;
}

/** lg_find: the newest version of a unit, or null (its seed then). */
function u2Find(f: Flash, unit: number): number | null {
  const a = u2Active(f);
  if (!a) return null;
  const d = u2Dir(f, a.half);
  let last = -1;
  for (let k = 0; k < U2_DATA && d[k] !== 0xff; k++) if (d[k] === unit) last = k;
  return last < 0 ? null : U2_LOG + a.half * U2_PAGES * PAGE + last * PAGE;
}

/** lg_start, lg_put, lg_done: every unit into the other half, its header,
 *  then the old half's directory erased. */
function u2Write(f: Flash, table: CartSlot[], slots: (Uint8Array | null)[]): void {
  const a = u2Active(f);
  const half = a ? a.half ^ 1 : 0, gen = a ? (a.gen + 1) & 255 : 0;
  const base = U2_LOG + half * U2_PAGES * PAGE, dir = base + U2_DATA * PAGE;
  for (let k = 0; k < U2_PAGES / 16; k++) f.erase(base + k * BLOCK);
  let j = 0;
  table.forEach((cs, k) => {
    const data = slots[k];
    if (!data) return;                                    // its seed then
    if (data.length !== PAGE) throw new CartError(`an Ultima II unit of ${data.length} bytes`);
    f.write(base + j * PAGE, data);
    f.write(dir + j, [cs.hdr & 0x7f]);
    j++;
  });
  if (!j) return;
  f.write(dir + 0xfe, [gen, gen ^ 0xff]);
  if (a) f.erase(U2_LOG + a.half * U2_PAGES * PAGE + U2_DATA * PAGE);
}

// -- Ultima VI's write log (page.s u6_find_log, page_u6x.s, u6log.py) -------------

interface U6Log { half: number; gen: number; dir: number; count: number }

/** u6_find_log: the valid half with the higher generation, and its
 *  directory -- the entries from the top down to the first erased key. */
function u6Log(f: Flash): U6Log | null {
  const top = (h: number) => {
    const e = f.read(U6_TOPS[h] - ENTRY, ENTRY);
    if (e[0] === 0xff) return null;
    if (e[0] !== 0xfe) return 0;
    if (e[1] !== 0x4c || e[2] !== 0x4f || e[3] !== 0x47) return null;
    if ((e[12] ^ e[14]) !== 0xff || (e[13] ^ e[15]) !== 0xff) return null;
    return e[12] | e[13] << 8;
  };
  const g = [top(0), top(1)];
  const half = g[1] !== null && (g[0] === null || g[1] > g[0]) ? 1 : g[0] !== null ? 0 : -1;
  if (half < 0) return null;
  let ep = U6_TOPS[half], count = 0;
  while (ep - ENTRY >= U6_BASES[half] && f.b[ep - ENTRY] !== 0xff) { ep -= ENTRY; count++; }
  return { half, gen: g[half]!, dir: ep, count };
}

/** DIR_LOOKUP: the first entry from the newest up whose key matches. */
function u6Lookup(f: Flash, log: U6Log, key: number[]): Uint8Array | null {
  for (let i = 0; i < log.count; i++) {
    const a = log.dir + i * ENTRY;
    if (key.every((c, k) => f.b[a + k] === c)) return f.read(a + KEYLEN, ENTRY - KEYLEN);
  }
  return null;
}

const fileKey = (name: string) => [0x2f, ...[...name].map(c => c.charCodeAt(0)), 0, 0, 0, 0, 0, 0, 0, 0];
const sectorKey = (s: number) => [1, 0, 6, s, 0, 0, 0, 0, 0, 0, 0, 0];
const a24 = (r: Uint8Array) => r[0] | r[1] << 8 | r[2] << 16;

/** f6_out: the chunk files the log has (with their links) in the disks'
 *  directory order, then the save-area sectors it has. */
function u6Records(f: Flash): U6Record[] {
  const log = u6Log(f);
  if (!log) return [];
  const out: U6Record[] = [];
  for (const name of U6_FILES) {
    const r = u6Lookup(f, log, fileKey(name));
    if (!r || !(r[5] & F6_LINKS) || r[3] < 1 || r[3] > MAXSEC) continue;
    const at = a24(r);
    out.push({ kind: "file", name, pages: Array.from({ length: r[3] }, (_, k) => f.read(at + k * PAGE, PAGE)) });
  }
  for (let s = 9; s <= 20; s++) {
    const r = u6Lookup(f, log, sectorKey(s));
    if (r) out.push({ kind: "sector", sector: s, data: f.read(a24(r), PAGE) });
  }
  return out;
}

/** x6_begin, f6_in, x6_commit: the other half erased, the records into it
 *  -- pages up from its base, entries down from one slot below its top --
 *  the header in the top slot, generation one more, then the old half erased. */
function u6Write(f: Flash, records: U6Record[]): void {
  const log = u6Log(f);
  const to = log ? log.half ^ 1 : 0, gen = log ? log.gen : 0xffff;
  for (let a = U6_BASES[to]; a < U6_TOPS[to]; a += BLOCK) f.erase(a);
  let wd = U6_BASES[to], we = U6_TOPS[to] - 2 * ENTRY;
  const entry = (key: number[], at: number, n: number, flags: number) => {
    if (wd > we) throw new CartError("the save does not fit Ultima VI's log");
    f.write(we, [...key, at & 255, at >> 8 & 255, at >> 16, n, 0, flags, 0, 0]);
    we -= ENTRY;
  };
  for (const r of records) {
    const at = wd, pages = r.kind === "file" ? r.pages : [r.data];
    if (wd + pages.length * PAGE > we) throw new CartError("the save does not fit Ultima VI's log");
    for (const pg of pages) { f.write(wd, pg); wd += PAGE; }
    if (r.kind === "file") entry(fileKey(r.name), at, r.pages.length, F6_LINKS);
    else entry(sectorKey(r.sector), at, 0, 0);
  }
  const g = (gen + 1) & 0xffff;
  f.write(U6_TOPS[to] - ENTRY, [0xfe, 0x4c, 0x4f, 0x47, 0, 0, 0, 0, 0, 0, 0, 0, g & 255, g >> 8, ~g & 255, ~g >> 8 & 255, 0, 0, 0, 0]);
  if (log) for (let a = U6_BASES[log.half]; a < U6_TOPS[log.half]; a += BLOCK) f.erase(a);
}
