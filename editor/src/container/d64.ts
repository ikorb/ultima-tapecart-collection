// A .d64 in memory: 35 tracks (or 40, read-only above 35), with or without
// the error bytes after the sectors.  Directory, BAM and files as a 1541
// keeps them; the model follows ultima/sim/fakedrive.py's Disk.

const SIZES = new Map<number, [number, boolean]>([   // length -> tracks, error bytes
  [174848, [35, false]], [175531, [35, true]], [196608, [40, false]], [197376, [40, true]],
]);

export function sectorsPerTrack(t: number): number {
  return t <= 17 ? 21 : t <= 24 ? 19 : t <= 30 ? 18 : 17;
}

export function isD64(b: Uint8Array): boolean {
  return SIZES.has(b.length);
}

export interface DirEntry {
  t: number; s: number; at: number;     // where the entry is: its directory sector, offset
  type: number;                         // the type byte ($81 SEQ, $82 PRG ...; bit 7 closed)
  start: [number, number];
  name: Uint8Array;                     // without its $A0 padding
  blocks: number;
}

export const TYPES = ["DEL", "SEQ", "PRG", "USR", "REL"];

export class D64 {
  readonly data: Uint8Array;
  readonly tracks: number;

  constructor(data: Uint8Array) {
    const g = SIZES.get(data.length);
    if (!g) throw new Error(`not a .d64 (${data.length} bytes)`);
    this.data = data.slice();
    this.tracks = g[0];
  }

  offset(t: number, s: number): number {
    if (t < 1 || t > this.tracks || s < 0 || s >= sectorsPerTrack(t))
      throw new Error(`no track ${t} sector ${s}`);
    let o = 0;
    for (let k = 1; k < t; k++) o += sectorsPerTrack(k);
    return (o + s) * 256;
  }

  sector(t: number, s: number): Uint8Array {
    const o = this.offset(t, s);
    return this.data.subarray(o, o + 256);
  }

  put(t: number, s: number, blk: Uint8Array): void {
    this.data.set(blk.subarray(0, 256), this.offset(t, s));
  }

  /** The disk's name from the BAM, without its padding. */
  diskName(): Uint8Array {
    return unpad(this.sector(18, 0).slice(0x90, 0xa0));
  }

  diskId(): Uint8Array {
    return this.sector(18, 0).slice(0xa2, 0xa4);
  }

  isFree(t: number, s: number): boolean {
    return (this.sector(18, 0)[4 * t + 1 + (s >> 3)] & (1 << (s & 7))) !== 0;
  }

  setFree(t: number, s: number, free: boolean): void {
    const bam = this.sector(18, 0), e = 4 * t, byte = e + 1 + (s >> 3), bit = 1 << (s & 7);
    const was = (bam[byte] & bit) !== 0;
    if (free && !was) { bam[byte] |= bit; bam[e]++; }
    else if (!free && was) { bam[byte] &= ~bit; bam[e]--; }
  }

  /** The first free sector from track 17 down, then 19 up (fakedrive's order). */
  alloc(): [number, number] {
    const order: number[] = [];
    for (let t = 17; t >= 1; t--) order.push(t);
    for (let t = 19; t <= 35; t++) order.push(t);
    for (const t of order)
      for (let s = 0; s < sectorsPerTrack(t); s++)
        if (this.isFree(t, s)) { this.setFree(t, s, false); return [t, s]; }
    throw new Error("72, DISK FULL");
  }

  *entries(): Generator<DirEntry> {
    let t = 18, s = 1;
    const seen = new Set<number>();
    while (t) {
      const key = t * 256 + s;
      if (seen.has(key)) break;               // a looped directory
      seen.add(key);
      const blk = this.sector(t, s);
      for (let i = 0; i < 8; i++) {
        const e = blk.subarray(i * 32, i * 32 + 32);
        yield { t, s, at: i * 32, type: e[2], start: [e[3], e[4]], name: unpad(e.slice(5, 21)),
                blocks: e[30] | e[31] << 8 };
      }
      [t, s] = [blk[0], blk[1]];
      if (!this.valid(t, s)) break;           // a last sector's link that is not 0 / a sector
    }
  }

  valid(t: number, s: number): boolean {
    return t >= 1 && t <= this.tracks && s >= 0 && s < sectorsPerTrack(t);
  }

  /** Files in the directory (not deleted). */
  files(): DirEntry[] {
    return [...this.entries()].filter(e => (e.type & 7) !== 0);
  }

  find(name: Uint8Array): DirEntry | undefined {
    return this.files().find(e => same(e.name, name));
  }

  chain(e: DirEntry): [number, number][] {
    const out: [number, number][] = [];
    let [t, s] = e.start;
    const seen = new Set<number>();
    while (t) {
      if (seen.has(t * 256 + s)) throw new Error("the file's chain loops");
      seen.add(t * 256 + s);
      out.push([t, s]);
      const blk = this.sector(t, s);
      [t, s] = [blk[0], blk[1]];
    }
    return out;
  }

  read(e: DirEntry): Uint8Array {
    const parts: Uint8Array[] = [];
    for (const [t, s] of this.chain(e)) {
      const blk = this.sector(t, s);
      parts.push(blk[0] ? blk.slice(2) : blk.slice(2, Math.max(2, blk[1] + 1)));
    }
    return concat(parts);
  }

  /** Replaces a file's contents.  With the same number of blocks the chain
   *  is reused, so only the file's own sectors change; otherwise the old
   *  chain is freed and a new one allocated (the BAM and the entry change). */
  rewrite(e: DirEntry, data: Uint8Array): void {
    const chunks = split(data);
    let secs = this.chain(e);
    const reuse = secs.length === chunks.length;
    if (!reuse) {
      for (const [t, s] of secs) this.setFree(t, s, true);
      secs = chunks.map(() => this.alloc());
      const d = this.sector(e.t, e.s);
      d[e.at + 3] = secs[0][0];
      d[e.at + 4] = secs[0][1];
      d[e.at + 30] = secs.length & 255;
      d[e.at + 31] = secs.length >> 8;
    }
    this.writeChain(secs, chunks, reuse);
  }

  /** A new file, in the first unused directory entry. */
  create(name: Uint8Array, data: Uint8Array, type = 0x81): void {
    const free = [...this.entries()].find(e => (e.type & 7) === 0);
    if (!free) throw new Error("72, DISK FULL (the directory)");
    const chunks = split(data);
    const secs = chunks.map(() => this.alloc());
    this.writeChain(secs, chunks);
    const d = this.sector(free.t, free.s);
    const ent = new Uint8Array(30).fill(0);
    ent[0] = type;
    ent[1] = secs[0][0];
    ent[2] = secs[0][1];
    ent.fill(0xa0, 3, 19);
    ent.set(name.subarray(0, 16), 3);
    ent[28] = secs.length & 255;
    ent[29] = secs.length >> 8;
    d.set(ent, free.at + 2);
  }

  /** With `keep`, the bytes after the data in the last sector stay as they
   *  were (whatever the drive left there), so an unchanged file is unchanged. */
  private writeChain(secs: [number, number][], chunks: Uint8Array[], keep = false): void {
    secs.forEach(([t, s], i) => {
      const blk = keep ? this.sector(t, s).slice() : new Uint8Array(256);
      if (i + 1 < secs.length) { blk[0] = secs[i + 1][0]; blk[1] = secs[i + 1][1]; }
      else { blk[0] = 0; blk[1] = chunks[i].length + 1; }
      blk.set(chunks[i], 2);
      this.put(t, s, blk);
    });
  }
}

/** A freshly formatted disk: everything free but the BAM and the directory. */
export function blankD64(name: string, id = "2A"): Uint8Array {
  const data = new Uint8Array(174848);
  const d = new D64(data);
  const bam = new Uint8Array(256);
  bam[0] = 18; bam[1] = 1; bam[2] = 0x41;
  for (let t = 1; t <= 35; t++) {
    const n = sectorsPerTrack(t);
    let bits = (2 ** n) - 1;
    if (t === 18) bits &= ~0b11;
    bam[4 * t] = popcount(bits);
    bam[4 * t + 1] = bits & 255; bam[4 * t + 2] = (bits >> 8) & 255; bam[4 * t + 3] = bits >> 16;
  }
  bam.fill(0xa0, 0x90, 0xab);
  for (let k = 0; k < Math.min(16, name.length); k++) bam[0x90 + k] = name.charCodeAt(k);
  bam[0xa2] = id.charCodeAt(0); bam[0xa3] = id.charCodeAt(1);
  bam[0xa5] = 0x32; bam[0xa6] = 0x41;
  d.put(18, 0, bam);
  const dir = new Uint8Array(256);
  dir[1] = 0xff;
  d.put(18, 1, dir);
  return d.data;
}

function popcount(v: number): number {
  let n = 0;
  for (; v; v >>>= 1) n += v & 1;
  return n;
}

function split(data: Uint8Array): Uint8Array[] {
  const out: Uint8Array[] = [];
  for (let i = 0; i < data.length; i += 254) out.push(data.subarray(i, i + 254));
  return out.length ? out : [new Uint8Array(0)];
}

function unpad(b: Uint8Array): Uint8Array {
  let n = b.length;
  while (n > 0 && b[n - 1] === 0xa0) n--;
  return b.slice(0, n);
}

export function same(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

export function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

/** PETSCII bytes from an ASCII string (capitals stay capitals: the
 *  directory's upper-case character set). */
export function petscii(s: string): Uint8Array {
  return Uint8Array.from([...s].map(c => c.charCodeAt(0)));
}

/** A directory name as text (its upper-case PETSCII shown as ASCII). */
export function nameText(b: Uint8Array): string {
  return [...b].map(c => c >= 0x20 && c < 0x7f ? String.fromCharCode(c)
                        : c >= 0xc1 && c <= 0xda ? String.fromCharCode(c - 0x80) : "?").join("");
}
