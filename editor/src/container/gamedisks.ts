// The games' own disks, where the original games keep their saves: which
// disk is which (the BAM's name, as the launcher's disk export checks it),
// and where on it each slot of the launcher's save file lives -- whole
// sectors, or a PRG file without its load address.  The same tables as the
// build's xfer descriptions (build/xfer.json; tests/gamedisks.test.ts
// compares the two).

import { D64, petscii, type DirEntry } from "./d64.ts";
import type { Ucsv, SaveSector } from "./ucsv.ts";

export type Slot =
  | { kind: "raw"; sectors: [number, number][] }
  | { kind: "file"; name: string; load: number; lo: number; hi: number; optional: boolean };

export interface GameDisk {
  game: number;
  label: string;
  names: string[];              // the BAM's disk name: the Trilogy's, then another edition's (the cart takes both)
  id: string | null;            // the disk ID, where the game checks it (Ultima VI)
  check: [number, number, number, number] | null;   // t, s, offset, value (Ultima IV's disk number)
  first: number;                // the index of its first slot in the game's save file
  slots: Slot[];
  total: number;                // the game's slot count in the save file
}

const raw = (...ts: [number, number][]): Slot => ({ kind: "raw", sectors: ts });
const run = (t: number, from: number, n: number): Slot => raw(...Array.from({ length: n }, (_, k) => [t, from + k] as [number, number]));
const file = (name: string, load: number, lo: number, hi = lo, optional = false): Slot =>
  ({ kind: "file", name, load, lo, hi, optional });

export const DISKS: GameDisk[] = [
  { game: 1, label: "Ultima I", names: ["ULTIMA I"], id: null, check: null, first: 0, total: 5,
    // RO is optional here too: a disk on which no character was ever made has none
    slots: [file("RO", 0xb000, 64, 64, true), ...[0, 1, 2, 3].map(k => file(`P${k}`, 0x81e2, 458, 458, true))] },
  { game: 2, label: "Player", names: ["PLAYER DISK", "U II-PLAYER DISK"], id: null, check: null, first: 0, total: 12,
    // MOB/MON optional for reading: another release's Player disk has no files at all, only the record
    slots: [...["00", "10", "20", "30", "40"].map(n => file(`MOB ${n}`, 0x3000, 256, 256, true)),
            ...["00", "03", "10", "20", "30", "40"].map(n => file(`MON ${n}`, 0x8f00, 256, 256, true)),
            raw([35, 16])] },
  { game: 3, label: "Scenario", names: ["PLAYER MASTER", "ULTIMA III-SCEN."], id: null, check: null, first: 0, total: 5,
    slots: [run(15, 2, 16), run(15, 18, 1), run(16, 12, 5), run(16, 17, 1), run(16, 18, 1)] },
  { game: 4, label: "Britannia", names: ["U4 DISK C", "BRITANNIA"], id: null, check: [1, 0, 0, 2], first: 0, total: 5,
    slots: [raw([13, 19]), raw([13, 20]), raw([14, 0]), raw([14, 1]), raw([14, 2])] },
  { game: 5, label: "Britannia (2A)", names: ["BRITANNIA"], id: null, check: null, first: 0, total: 6,
    slots: [file("ROSTER", 0x1000, 1024, 1025), file("PRTY.DATA", 0xbc00, 48), file("LIST", 0x4a00, 512),
            file("SLIST", 0x4a00, 512), file("TLIST", 0x4a00, 256, 512)] },
  { game: 5, label: "Underworld (2B)", names: ["UNDERWORLD"], id: null, check: null, first: 5, total: 6,
    slots: [file("TLIST", 0x4a00, 256, 512)] },
  // Ultima VI: the save area only (track 6 sectors 9-20); its chunk files are not edited
  { game: 6, label: "Surface (1A)", names: ["SURFACE"], id: "SU", check: null, first: 0, total: 0,
    slots: [run(6, 9, 12)] },
];

function unpadded(b: Uint8Array): string {
  let n = b.length;
  while (n > 0 && (b[n - 1] === 0xa0 || b[n - 1] === 0)) n--;
  return String.fromCharCode(...b.subarray(0, n));
}

export interface Recognised { disk: GameDisk; original: boolean; diskName: string }

/** Which game disk an image is, if any: by its name -- the Trilogy's or
 *  another edition's, both of which the cart's launcher takes.  `original`
 *  says the launcher would take it for its own import: the name exactly as
 *  it compares it ($A0-padded), the ID where it checks one, and the extra
 *  byte the game checks (Ultima IV's disk number, which also tells its 1986
 *  "BRITANNIA" from Ultima V's).  A disk that fails those still opens, as the
 *  first whose name it carries, with original false. */
export function recognise(image: Uint8Array): Recognised | null {
  const d = new D64(image);
  const bam = d.sector(18, 0);
  const name = unpadded(bam.subarray(0x90, 0xa0));
  const id = String.fromCharCode(bam[0xa2], bam[0xa3]);
  let fallback: Recognised | null = null;
  for (const disk of DISKS) {
    const k = disk.names.indexOf(name);
    if (k < 0) continue;
    if (disk.id && id !== disk.id) continue;
    const checked = !disk.check || d.sector(disk.check[0], disk.check[1])[disk.check[2]] === disk.check[3];
    const exact = Array.from({ length: 16 }, (_, i) => i < disk.names[k].length ? disk.names[k].charCodeAt(i) : 0xa0)
      .every((c, i) => bam[0x90 + i] === c);
    const r = { disk, original: checked && exact, diskName: name };
    if (r.original) return r;
    fallback ??= r;
  }
  return fallback;
}

function fileEntry(d: D64, name: string): DirEntry | undefined {
  return d.files().find(e => (e.type & 7) === 2 && e.name.length === name.length
    && e.name.every((c, i) => c === name.charCodeAt(i)));
}

/** The save as the launcher's file would hold it, read off a game disk:
 *  the slots of the other disk (Ultima V's 2B for a 2A, and back) are null. */
export function readSave(image: Uint8Array, disk: GameDisk): Ucsv {
  const d = new D64(image);
  if (disk.game === 6) {
    const records: SaveSector[] = Array.from({ length: 12 }, (_, k) =>
      ({ kind: "sector", sector: 9 + k, data: d.sector(6, 9 + k).slice() }));
    return { game: 6, version: 1, slots: [], records };
  }
  const slots: (Uint8Array | null)[] = new Array(disk.total).fill(null);
  disk.slots.forEach((s, k) => {
    if (s.kind === "raw") {
      const out = new Uint8Array(256 * s.sectors.length);
      s.sectors.forEach(([t, sc], j) => out.set(d.sector(t, sc), 256 * j));
      slots[disk.first + k] = out;
    } else {
      const e = fileEntry(d, s.name);
      if (!e) {
        if (s.optional) return;
        throw new Error(`the disk has no file ${s.name}`);
      }
      // the load address is not checked: the shipped U1 disk's RO says $2000, and the game loads it to $B000
      const data = d.read(e);
      if (data.length < 2) throw new Error(`${s.name} is empty`);
      slots[disk.first + k] = data.slice(2);
    }
  });
  return { game: disk.game, version: 1, slots, records: [] };
}

/** The image with the save written back into its places.  Only slots that
 *  differ from `before` are written; a file keeps its chain if its length
 *  in blocks is the same (it always is: edits never change a length). */
export function writeSave(image: Uint8Array, disk: GameDisk, save: Ucsv, before: Ucsv): Uint8Array {
  const d = new D64(image);
  if (disk.game === 6) {
    for (const r of save.records) if (r.kind === "sector") d.put(6, r.sector, r.data);
    return d.data;
  }
  disk.slots.forEach((s, k) => {
    const now = save.slots[disk.first + k], was = before.slots[disk.first + k];
    if (!now || (was && now.length === was.length && now.every((b, i) => b === was[i]))) return;
    if (s.kind === "raw") s.sectors.forEach(([t, sc], j) => d.put(t, sc, now.subarray(256 * j, 256 * j + 256)));
    else {
      const e = fileEntry(d, s.name);
      const data = new Uint8Array(now.length + 2);
      const old = e ? d.read(e) : null;                // the file keeps its own load address
      const load = old && old.length >= 2 ? old[0] | old[1] << 8 : s.load;
      data[0] = load & 255; data[1] = load >> 8;
      data.set(now, 2);
      if (e) d.rewrite(e, data);
      else d.create(petscii(s.name), data, 0x82);
    }
  });
  return d.data;
}
