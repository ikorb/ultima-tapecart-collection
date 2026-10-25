// The launcher's save file (docs/save-format.md, written by
// asm/page_file.s): "UCSV", the game (1-6), the version (1), the body, two
// check bytes.  Ultima I-V's body is slots, Ultima VI's records.

export const MAGIC = [0x55, 0x43, 0x53, 0x56];            // "UCSV"
export const VERSION = 1;
export const NAMES = ["", "ULTIMA I SAVE", "ULTIMA II SAVE", "ULTIMA III SAVE",
                      "ULTIMA IV SAVE", "ULTIMA V SAVE", "ULTIMA VI SAVE"];

/** An Ultima VI chunk file: its name and its disk pages in chain order,
 *  link bytes included, as the game wrote them. */
export interface ChunkFile { kind: "file"; name: string; pages: Uint8Array[] }
/** An Ultima VI save-area sector: Surface (1A) track 6, sector 9-20. */
export interface SaveSector { kind: "sector"; sector: number; data: Uint8Array }
export type U6Record = ChunkFile | SaveSector;

export interface Ucsv {
  game: number;                       // 1-6
  version: number;
  slots: (Uint8Array | null)[];       // Ultima I-V; null = an empty slot
  records: U6Record[];                // Ultima VI, in file order
}

export class UcsvError extends Error {}

export function checkBytes(body: Uint8Array): [number, number] {
  let s1 = 0, s2 = 0;
  for (const b of body) {
    s1 = (s1 + b) & 255;
    s2 = (s2 + s1) & 255;
  }
  return [s1, s2];
}

export function isUcsv(b: Uint8Array): boolean {
  return b.length >= 8 && MAGIC.every((m, i) => b[i] === m);
}

const U6_FILE = /^(S[A-H][A-H]|D[A-E][A-D])$/;          // 64 surface, 20 dungeon (5 levels x 4)

/** Decodes a whole file; throws UcsvError on anything the page would refuse. */
export function decode(b: Uint8Array): Ucsv {
  if (!isUcsv(b)) throw new UcsvError("not a saved game file of the collection (no \"UCSV\")");
  const game = b[4], version = b[5];
  if (game < 1 || game > 6) throw new UcsvError(`unknown game number ${game}`);
  if (version !== VERSION) throw new UcsvError(`version ${version}, this editor knows ${VERSION}`);
  const [s1, s2] = checkBytes(b.subarray(0, b.length - 2));
  if (s1 !== b[b.length - 2] || s2 !== b[b.length - 1])
    throw new UcsvError("the check bytes do not match: the file is damaged");
  const end = b.length - 2;
  let i = 6;
  const need = (n: number) => {
    if (i + n > end) throw new UcsvError("the file is cut short");
  };
  const out: Ucsv = { game, version, slots: [], records: [] };
  if (game !== 6) {
    need(1);
    const n = b[i++];
    for (let k = 0; k < n; k++) {
      need(3);
      const flag = b[i], len = b[i + 1] | b[i + 2] << 8;
      i += 3;
      if (flag === 0) {
        if (len !== 0) throw new UcsvError(`slot ${k + 1}: empty with a length`);
        out.slots.push(null);
      } else if (flag === 1) {
        need(len);
        out.slots.push(b.slice(i, i + len));
        i += len;
      } else throw new UcsvError(`slot ${k + 1}: flag ${flag}`);
    }
  } else {
    for (;;) {
      need(1);
      const kind = b[i++];
      if (kind === 0) break;
      if (kind === 1) {
        need(4);
        const name = String.fromCharCode(b[i], b[i + 1], b[i + 2]), n = b[i + 3];
        i += 4;
        if (!U6_FILE.test(name)) throw new UcsvError(`no chunk file "${name}" in Ultima VI`);
        if (n < 1 || n > 20) throw new UcsvError(`chunk file ${name}: ${n} pages`);
        need(256 * n);
        const pages: Uint8Array[] = [];
        for (let p = 0; p < n; p++) pages.push(b.slice(i + 256 * p, i + 256 * (p + 1)));
        i += 256 * n;
        out.records.push({ kind: "file", name, pages });
      } else if (kind === 2) {
        need(257);
        const sector = b[i];
        if (sector < 9 || sector > 20) throw new UcsvError(`save-area sector ${sector}`);
        out.records.push({ kind: "sector", sector, data: b.slice(i + 1, i + 257) });
        i += 257;
      } else throw new UcsvError(`record kind ${kind}`);
    }
  }
  if (i !== end) throw new UcsvError("there is something after the end of the data");
  return out;
}

/** Encodes as the page writes it; decode(encode(x)) is x. */
export function encode(u: Ucsv): Uint8Array {
  const parts: number[] = [...MAGIC, u.game, u.version];
  const push = (a: ArrayLike<number>) => { for (let k = 0; k < a.length; k++) parts.push(a[k]); };
  if (u.game !== 6) {
    parts.push(u.slots.length);
    for (const s of u.slots) {
      if (s === null) parts.push(0, 0, 0);
      else { parts.push(1, s.length & 255, s.length >> 8); push(s); }
    }
  } else {
    for (const r of u.records) {
      if (r.kind === "file") {
        parts.push(1, ...[...r.name].map(c => c.charCodeAt(0)), r.pages.length);
        for (const p of r.pages) push(p);
      } else {
        parts.push(2, r.sector);
        push(r.data);
      }
    }
    parts.push(0);
  }
  const body = Uint8Array.from(parts);
  const [s1, s2] = checkBytes(body);
  const out = new Uint8Array(body.length + 2);
  out.set(body);
  out[body.length] = s1;
  out[body.length + 1] = s2;
  return out;
}

/** An Ultima VI chunk file's contents: bytes 2-255 of each page, of the last
 *  only up to the index its link gives. */
export function chunkContents(f: ChunkFile): Uint8Array {
  const parts: Uint8Array[] = [];
  f.pages.forEach((p, k) => {
    const last = k === f.pages.length - 1;
    parts.push(p.subarray(2, last ? Math.max(2, p[1] + 1) : 256));
  });
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}
