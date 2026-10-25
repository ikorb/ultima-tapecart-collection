// The field engine: a game's save as named byte areas, fields that read and
// write values at an offset in one, and the edits as byte patches (undo,
// redo, and what changed).  A field nobody edits is never re-encoded, so
// every byte the editor does not understand stays as it was.

import type { Ucsv, SaveSector } from "../container/ucsv.ts";

// -- areas --------------------------------------------------------------------

/** A run of bytes of the save: one slot, several slots back to back, or
 *  Ultima VI's save area (sectors that may be missing from the file). */
export interface Area {
  key: string;
  label: string;
  length: number;
  base: number;                              // the address of byte 0 in the game's memory, for display
  has(i: number): boolean;                   // is byte i in the file?
  get(i: number): number;                    // 0 where missing
  set(i: number, v: number): void;
}

export function slotArea(save: Ucsv, key: string, label: string, slots: number[], base = 0): Area | null {
  const parts = slots.map(k => save.slots[k]);
  if (parts.some(p => !p)) return null;
  const arrs = parts as Uint8Array[];
  const at = (i: number): [Uint8Array, number] => {
    for (const a of arrs) { if (i < a.length) return [a, i]; i -= a.length; }
    throw new RangeError(`${key}: byte ${i}`);
  };
  return {
    key, label, base, length: arrs.reduce((n, a) => n + a.length, 0),
    has: i => i >= 0 && i < arrs.reduce((n, a) => n + a.length, 0),
    get: i => { const [a, j] = at(i); return a[j]; },
    set: (i, v) => { const [a, j] = at(i); a[j] = v & 255; },
  };
}

/** One slot that may be missing from the file (an Ultima I roster seat that
 *  never held a character): its bytes are not there, the first edit adds the
 *  slot (`length` zeros, then the edit), and it goes again when its bytes are
 *  all zero once more (an undo).  A slot that was there stays. */
export function optionalSlotArea(save: Ucsv, key: string, label: string, slot: number, length: number, base = 0): Area {
  let added = false;
  const len = () => save.slots[slot]?.length ?? length;
  return {
    key, label, base, length: len(),
    has: i => i >= 0 && !!save.slots[slot] && i < len(),
    get: i => save.slots[slot]?.[i] ?? 0,
    set: (i, v) => {
      let a = save.slots[slot];
      if (!a) { a = save.slots[slot] = new Uint8Array(length); added = true; }
      a[i] = v & 255;
      if (added && a.every(b => b === 0)) { save.slots[slot] = null; added = false; }
    },
  };
}

/** Ultima VI's save area, $5400-$5FFF: Surface track 6 sectors 9-20.  With
 *  the original disk's bytes, a sector the file lacks reads as those, and
 *  the first edit in it adds it to the file (in sector order), and it goes
 *  again when its bytes are the original's once more (an undo); without,
 *  its bytes are missing. */
export function u6SaveArea(save: Ucsv, original?: Uint8Array): Area {
  const secs = new Map<number, SaveSector>();
  for (const r of save.records) if (r.kind === "sector") secs.set(r.sector, r);
  const sec = (i: number) => secs.get(9 + (i >> 8));
  const added = new Set<SaveSector>();
  return {
    key: "save", label: "Save area (1A track 6, sectors 9-20)", length: 12 * 256, base: 0x5400,
    has: i => i >= 0 && i < 3072 && (!!original || sec(i) !== undefined),
    get: i => sec(i)?.data[i & 255] ?? original?.[i] ?? 0,
    set: (i, v) => {
      let r = sec(i);
      if (!r) {
        if (!original) throw new RangeError(`sector ${9 + (i >> 8)} is not in the file`);
        const sector = 9 + (i >> 8), base = i & ~255;
        r = { kind: "sector", sector, data: original.slice(base, base + 256) };
        const after = save.records.findIndex(x => x.kind === "sector" && x.sector > sector);
        save.records.splice(after < 0 ? save.records.length : after, 0, r);
        secs.set(sector, r);
        added.add(r);
      }
      r.data[i & 255] = v & 255;
      const base = i & ~255;
      if (original && added.has(r) && r.data.every((b, k) => b === original[base + k])) {
        save.records.splice(save.records.indexOf(r), 1);
        secs.delete(r.sector);
        added.delete(r);
      }
    },
  };
}

// -- fields -------------------------------------------------------------------

export type Conf = "verified" | "reference";

export type Charset =
  | "ascii"      // plain ASCII, NUL padded (Ultima I)
  | "high"       // ASCII with bit 7 set, NUL terminated (Ultima II-IV)
  | "u5"         // bit 7 set on all but the last letter, NUL padded (Ultima V)
  | "screen";    // screen codes, capitals $41-$5A, small $01-$1A, NUL terminated (Ultima VI)

export type Enc =
  | { t: "u8" }
  | { t: "u16le" }
  | { t: "bcd"; n: number; le?: boolean }          // n bytes, the highest digits first (le: last)
  | { t: "text"; n: number; cs: Charset; upper?: boolean }
  | { t: "enum"; values: [number, string][] }       // one byte
  | { t: "flag"; mask: number }                     // a checkbox: (byte & mask) != 0
  | { t: "bits"; mask: number }                     // a number in the mask's bits, the rest kept
  | { t: "nonzero"; on: number }                    // a checkbox: byte != 0, set as `on`
  | { t: "signed"; } ;                              // one byte, -128..127

export type Value = number | string | boolean;

export interface Field {
  id: string;                // unique within the game
  label: string;
  area: string;
  at: number;
  enc: Enc;
  min?: number;
  max?: number;
  conf: Conf;
  src: string;               // where the meaning comes from
  note?: string;
  readOnly?: boolean;
  /** The game's own limit, where it is known: a value beyond it is allowed
   *  (the bytes hold it, and trainers write such values) but flagged, as
   *  the game may put it back. */
  rule?: Rule;
  /** Further writes an edit implies (U4's class mask with the class). */
  also?: (v: Value, w: Writer) => void;
}

export interface Rule { min?: number; max?: number; step?: number; text: string }

/** Is a value outside the field's game rule? */
export function beyond(f: Field, v: Value | undefined): boolean {
  const r = f.rule;
  if (!r || typeof v !== "number") return false;
  return (r.max !== undefined && v > r.max) || (r.min !== undefined && v < r.min) || (!!r.step && v % r.step !== 0);
}

export function size(e: Enc): number {
  switch (e.t) {
    case "u16le": return 2;
    case "bcd": return e.n;
    case "text": return e.n;
    default: return 1;
  }
}

export function bcdValid(b: number): boolean {
  return (b & 15) < 10 && (b >> 4) < 10;
}

export function read(a: Area, f: Field): Value | undefined {
  const n = size(f.enc);
  for (let k = 0; k < n; k++) if (!a.has(f.at + k)) return undefined;
  const b = (k: number) => a.get(f.at + k);
  const e = f.enc;
  switch (e.t) {
    case "u8": return b(0);
    case "signed": return b(0) < 128 ? b(0) : b(0) - 256;
    case "u16le": return b(0) | b(1) << 8;
    case "bcd": {
      let v = 0;
      for (let k = 0; k < e.n; k++) { const x = b(e.le ? e.n - 1 - k : k); v = v * 100 + (x >> 4) * 10 + (x & 15); }
      return v;
    }
    case "enum": return b(0);
    case "flag": return (b(0) & e.mask) !== 0;
    case "bits": return (b(0) & e.mask) >> shift(e.mask);
    case "nonzero": return b(0) !== 0;
    case "text": {
      let s = "";
      for (let k = 0; k < e.n; k++) {
        const c = b(k);
        if (c === 0) break;
        s += charOf(c, e.cs);
        if (e.cs === "u5" && (c & 0x80) === 0) break;
      }
      return s;
    }
  }
}

/** The lowest set bit's position. */
function shift(mask: number): number {
  let n = 0;
  while (mask && !(mask & 1 << n)) n++;
  return n;
}

/** Is every byte of a BCD field a valid BCD digit pair? */
export function bcdOk(a: Area, f: Field): boolean {
  if (f.enc.t !== "bcd") return true;
  for (let k = 0; k < f.enc.n; k++) if (!bcdValid(a.get(f.at + k))) return false;
  return true;
}

function charOf(c: number, cs: Charset): string {
  if (cs === "screen") {
    if (c >= 1 && c <= 26) return String.fromCharCode(0x60 + c);
    return c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : "?";
  }
  const a = cs === "ascii" ? c : c & 0x7f;
  return a >= 0x20 && a < 0x7f ? String.fromCharCode(a) : "?";
}

/** The longest name a text field holds: all its bytes in Ultima V's
 *  encoding (the last letter is the one without bit 7), one fewer where a
 *  NUL ends the name. */
export function maxLetters(e: Enc): number {
  return e.t !== "text" ? 0 : e.cs === "u5" ? e.n : e.n - 1;
}

const NAME_OK: Record<Charset, RegExp> = {
  ascii: /^[ -~]*$/,
  high: /^[ -_a-z]*$/,
  u5: /^[ -~]*$/,
  screen: /^[ A-Za-z0-9.,'!?-]*$/,
};

/** Why a value cannot be stored in the field, or null. */
export function invalid(f: Field, v: Value): string | null {
  const e = f.enc;
  if (e.t === "text") {
    const s = e.upper ? String(v).toUpperCase() : String(v);
    if (s.length > maxLetters(e)) return `at most ${maxLetters(e)} letters`;
    if (s.length === 0) return "a name, at least one letter";
    if (!NAME_OK[e.cs].test(s)) return "letters the game cannot show";
    return null;
  }
  if (e.t === "flag" || e.t === "nonzero") return null;
  const n = Number(v);
  if (!Number.isInteger(n)) return "a whole number";
  const max = f.max ?? (e.t === "bcd" ? 10 ** (2 * e.n) - 1 : e.t === "u16le" ? 65535
                        : e.t === "signed" ? 127 : e.t === "bits" ? e.mask >> shift(e.mask) : 255);
  const min = f.min ?? (e.t === "signed" ? -128 : 0);
  if (n < min || n > max) return `${min} to ${max}`;
  if (e.t === "enum" && !e.values.some(([k]) => k === n) && f.min === undefined) return "not one of the choices";
  return null;
}

export function encode(f: Field, v: Value): number[] {
  const e = f.enc;
  switch (e.t) {
    case "u8": case "enum": return [Number(v) & 255];
    case "signed": return [Number(v) & 255];
    case "u16le": return [Number(v) & 255, Number(v) >> 8 & 255];
    case "bcd": {
      const out: number[] = [];
      let n = Number(v);
      for (let k = 0; k < e.n; k++) {
        const p = n % 100;
        out.unshift((Math.floor(p / 10) << 4) | p % 10);
        n = Math.floor(n / 100);
      }
      return e.le ? out.reverse() : out;
    }
    case "text": {
      let s = String(v);
      if (e.upper) s = s.toUpperCase();
      const out = new Array<number>(e.n).fill(0);
      [...s].forEach((ch, k) => {
        const c = ch.charCodeAt(0);
        if (e.cs === "screen") out[k] = c >= 0x61 && c <= 0x7a ? c - 0x60 : c;
        else if (e.cs === "ascii") out[k] = c;
        else if (e.cs === "u5") out[k] = k < s.length - 1 ? c | 0x80 : c;
        else out[k] = c | 0x80;
      });
      return out;
    }
    case "flag": case "nonzero": case "bits": return [];     // handled with the old byte in Doc.edit()
  }
}

// -- the document: areas, edits, undo ------------------------------------------

export interface Patch { area: string; at: number; before: number[]; after: number[] }

/** One undo step: its patches, and what it did, for the Undo button's tooltip. */
export interface Step { label: string; patches: Patch[] }

export interface Writer { set(field: Field, v: Value): void; setByte(area: string, at: number, v: number): void }

export class Doc {
  readonly areas = new Map<string, Area>();
  private undoStack: Step[] = [];
  private redoStack: Step[] = [];

  /** The bytes as the file was opened. */
  readonly original = new Map<string, Uint8Array>();

  constructor(areas: (Area | null)[]) {
    for (const a of areas) if (a) this.areas.set(a.key, a);
    for (const a of this.areas.values())
      this.original.set(a.key, Uint8Array.from({ length: a.length }, (_, i) => a.get(i)));
  }

  area(key: string): Area {
    const a = this.areas.get(key);
    if (!a) throw new Error(`no area ${key}`);
    return a;
  }

  has(f: Field): boolean {
    const a = this.areas.get(f.area);
    return !!a && read(a, f) !== undefined;
  }

  value(f: Field): Value | undefined {
    const a = this.areas.get(f.area);
    return a ? read(a, f) : undefined;
  }

  originalValue(f: Field): Value | undefined {
    const o = this.original.get(f.area), a = this.areas.get(f.area);
    if (!o || !a) return undefined;
    return read({ ...a, get: i => o[i] }, f);
  }

  /** One user edit (with whatever it implies) as one undo step. */
  edit(fn: (w: Writer) => void, label = "an edit"): void {
    const step: Patch[] = [];
    const setByte = (area: string, at: number, v: number) => {
      const a = this.area(area), old = a.get(at);
      if (old === (v & 255)) return;
      a.set(at, v);
      step.push({ area, at, before: [old], after: [v & 255] });
    };
    const w: Writer = {
      setByte,
      set: (f, v) => {
        const why = invalid(f, v);
        if (why) throw new RangeError(`${f.label}: ${why}`);
        const a = this.area(f.area);
        if (f.enc.t === "flag") setByte(f.area, f.at, v ? a.get(f.at) | f.enc.mask : a.get(f.at) & ~f.enc.mask);
        else if (f.enc.t === "nonzero") setByte(f.area, f.at, v ? f.enc.on : 0);
        else if (f.enc.t === "bits")
          setByte(f.area, f.at, a.get(f.at) & ~f.enc.mask | Number(v) << shift(f.enc.mask) & f.enc.mask);
        else encode(f, v).forEach((b, k) => setByte(f.area, f.at + k, b));
        f.also?.(v, w);
      },
    };
    try { fn(w); } catch (e) {                        // all of it or nothing
      for (const p of [...step].reverse()) p.before.forEach((b, k) => this.area(p.area).set(p.at + k, b));
      throw e;
    }
    if (step.length) { this.undoStack.push({ label, patches: step }); this.redoStack = []; }
  }

  set(f: Field, v: Value, label?: string): void { this.edit(w => w.set(f, v), label ?? f.label); }

  /** A field's bytes as the file was opened (only its bits, for a flag), as one undo step. */
  revert(f: Field, label = `${f.label} as opened`): void {
    const o = this.original.get(f.area), a = this.area(f.area);
    if (!o) return;
    const mask = f.enc.t === "flag" || f.enc.t === "bits" ? f.enc.mask : 0xff;
    this.edit(w => { for (let k = 0; k < size(f.enc); k++) w.setByte(f.area, f.at + k, a.get(f.at + k) & ~mask | o[f.at + k] & mask); }, label);
  }

  /** Bytes as the file was opened, as one undo step. */
  revertBytes(bytes: [string, number][], label = "bytes as opened"): void {
    this.edit(w => { for (const [area, i] of bytes) w.setByte(area, i, this.original.get(area)![i]); }, label);
  }

  canUndo(): boolean { return this.undoStack.length > 0; }
  canRedo(): boolean { return this.redoStack.length > 0; }
  /** What Undo and Redo would do. */
  undoLabel(): string | null { return this.undoStack.at(-1)?.label ?? null; }
  redoLabel(): string | null { return this.redoStack.at(-1)?.label ?? null; }

  undo(): void {
    const step = this.undoStack.pop();
    if (!step) return;
    for (const p of [...step.patches].reverse()) p.before.forEach((b, k) => this.area(p.area).set(p.at + k, b));
    this.redoStack.push(step);
  }

  redo(): void {
    const step = this.redoStack.pop();
    if (!step) return;
    for (const p of step.patches) p.after.forEach((b, k) => this.area(p.area).set(p.at + k, b));
    this.undoStack.push(step);
  }

  /** Bytes that differ from the file as opened, per area. */
  changedBytes(): Map<string, number[]> {
    const out = new Map<string, number[]>();
    for (const a of this.areas.values()) {
      const o = this.original.get(a.key);
      if (!o) continue;
      const diff: number[] = [];
      for (let i = 0; i < a.length; i++) if (a.has(i) && a.get(i) !== o[i]) diff.push(i);
      if (diff.length) out.set(a.key, diff);
    }
    return out;
  }
}

// -- a game's description -------------------------------------------------------

/** A button: an edit of several fields at once (one undo step), or a field to
 *  go to (an empty inventory slot, its list opened). */
export interface Action {
  label: string;
  title?: string;
  run?: (w: Writer, d: Doc) => void;
  focus?: (d: Doc) => string | null;
  /** Why it cannot be done now, or null. */
  disabled?: (d: Doc) => string | null;
}

interface SectionBase {
  title: string;
  note?: string;
  actions?: Action[];
  /** A grid's "all"/"none" buttons (on unless false; only for grids of like fields). */
  bulk?: boolean;
}

export type Section =
  | SectionBase & { kind: "form"; fields: Field[] }
  | SectionBase & { kind: "grid"; fields: Field[] }
  | SectionBase & { kind: "records"; records: RecordDef[] }
  /** Rows of like fields under column headings (an inventory's slots); `fields` is every cell's field. */
  | SectionBase & { kind: "table"; columns: string[]; rows: TableRow[]; fields: Field[] };

export interface TableRow {
  label: string;
  cells: (Field | null)[];
  /** Nothing in the row (its other cells are then left blank). */
  empty?: (d: Doc) => boolean;
  /** What can be done with the row's contents (move it elsewhere ...). */
  menu?: (d: Doc) => Choice[];
}

export interface Choice { label: string; run: (w: Writer) => void; disabled?: string | null }

export function table(title: string, columns: string[], rows: TableRow[], note?: string, actions?: Action[]): Section {
  return { kind: "table", title, columns, rows, note, actions, fields: rows.flatMap(r => r.cells.filter((f): f is Field => !!f)) };
}

export interface RecordDef {
  key: string;
  title: (d: Doc) => string;
  present?: (d: Doc) => boolean;     // false: shown greyed (an empty roster place)
  /** A short note beside the title in the list (how many things it holds ...). */
  badge?: (d: Doc) => { text: string; title?: string } | null;
  /** A message to show instead of the sections (nothing to edit), or null. */
  empty?: (d: Doc) => string | null;
  /** Edits of the whole record (delete it ...), shown above it, also when it is empty. */
  actions?: Action[];
  /** Menus of such edits (copy another record into it ...). */
  menus?: RecordMenu[];
  sections: Section[];
}

export interface RecordMenu { label: string; choices: (d: Doc) => Choice[] }

/** Writes n bytes of one place over another (a whole record copied). */
export function copyBytes(w: Writer, d: Doc, from: [string, number], to: [string, number], n: number): void {
  const a = d.area(from[0]);
  for (let k = 0; k < n; k++) w.setByte(to[0], to[1] + k, a.get(from[1] + k));
}

export interface Tab { title: string; sections: Section[]; actions?: Action[] }

/** Something about the values the game may not like: where (a field's id,
 *  to go to) and what would put it right. */
export interface Warning { text: string; id?: string; fix?: Choice }

export interface GameView {
  game: number;
  title: string;
  doc: Doc;
  tabs: Tab[];
  /** Why the game's saves cannot be written yet, or null. */
  readOnly: string | null;
  /** Remarks about the file as a whole (missing sectors, empty slots). */
  remarks: string[];
  /** Consistency warnings for the current values. */
  warnings(): Warning[];
}

/** Every field of a view, with a path for the change list. */
export function allFields(v: GameView): { path: string; field: Field }[] {
  const out: { path: string; field: Field }[] = [];
  const walk = (secs: Section[], path: string) => {
    for (const s of secs) {
      if (s.kind === "records")
        for (const r of s.records) walk(r.sections, `${path} › ${r.title(v.doc)}`);
      else for (const f of s.fields) out.push({ path: `${path} › ${s.title}`, field: f });
    }
  };
  for (const t of v.tabs) walk(t.sections, t.title);
  return out;
}

/** The allowed value nearest to v under the field's rule (the step's
 *  multiples within min and max). */
export function withinRule(f: Field, v: number): number {
  const r = f.rule;
  if (!r) return v;
  const lo = r.min ?? 0, hi = r.max ?? Infinity;
  let n = Math.min(hi, Math.max(lo, v));
  if (r.step) {
    n = Math.round(n / r.step) * r.step;
    if (n > hi) n -= r.step;
    if (n < lo) n += r.step;
  }
  return n;
}

/** Grids of like fields: what "all" and "none" set them to, or null. */
export function bulkValues(s: Section): { all: Value; none: Value; allLabel: string; noneLabel: string } | null {
  if (s.kind !== "grid" || s.bulk === false || s.actions) return null;
  const fs = s.fields.filter(f => !f.readOnly);
  if (fs.length < 3 || fs.length !== s.fields.length) return null;
  const e = fs[0].enc;
  if (fs.every(f => f.enc.t === "flag" || f.enc.t === "nonzero")) return { all: true, none: false, allLabel: "All", noneLabel: "None" };
  if (!fs.every(f => f.enc.t === e.t && (e.t !== "bcd" || (f.enc.t === "bcd" && f.enc.n === e.n)))) return null;
  const maxes = new Set(fs.map(f => f.max ?? (f.enc.t === "bcd" ? 10 ** (2 * f.enc.n) - 1 : undefined)));
  const [max] = [...maxes];
  if (maxes.size !== 1 || max === undefined || fs.some(f => f.min !== undefined && f.min > 0)) return null;
  return { all: max, none: 0, allLabel: `All ${max}`, noneLabel: "All 0" };
}

/** Fields whose value is beyond the game's own limit. */
export function beyondRules(v: GameView): { path: string; field: Field; value: Value }[] {
  return allFields(v).flatMap(({ path, field }) => {
    const value = v.doc.value(field);
    return value !== undefined && beyond(field, value) ? [{ path, field, value }] : [];
  });
}

/** What differs from the file as opened, field by field. */
export function changes(v: GameView): { path: string; field: Field; before: Value | undefined; after: Value | undefined }[] {
  return allFields(v)
    .map(({ path, field }) => ({ path, field, before: v.doc.originalValue(field), after: v.doc.value(field) }))
    .filter(c => c.before !== c.after);
}

// -- helpers for the game tables -------------------------------------------------

export const u8 = { t: "u8" } as const;
export const u16 = { t: "u16le" } as const;
export const bcd1 = { t: "bcd", n: 1 } as const;
export const bcd2 = { t: "bcd", n: 2 } as const;
export const bcd3 = { t: "bcd", n: 3 } as const;
export const bcd4 = { t: "bcd", n: 4 } as const;

export function enumOf(names: string[], first = 0): Enc {
  return { t: "enum", values: names.map((n, k) => [first + k, n]) };
}

/** A list of fields of one encoding at consecutive offsets, e.g. counts of items. */
export function counts(area: string, at: number, names: string[], enc: Enc, base: Omit<Partial<Field>, "id">,
                       idPrefix: string, step = size(enc)): Field[] {
  return names.map((label, k) => ({
    conf: "reference", src: "", ...base,
    id: `${idPrefix}.${k}`, label, area, at: at + k * step, enc,
  } as Field)).filter(f => f.label !== "");
}
