// Ultima VI: the save area ($5400-$5FFF, Surface track 6 sectors 9-20) and
// the chunk files the game rewrote.  A file holds only what differs from
// the original disks, so sectors may be missing: their fields are shown as
// not in the file.
//
// Sources: the save game's layout (docs/reversing-notes/u6.md), with the parts
// the launcher page and the Avatar transfer read and write (asm/page.s i_u6,
// asm/page_u6t.s) verified on real saves; and the game's own cheat menu
// (T001, talking to yourself), whose script names the Talk overlay's
// functions (str, level, exp, flag, poisoned, cure, karma, the spells) --
// each followed into the overlay (1A track 4 sectors 9-20 at $C000) to the
// bytes it reads and writes: poisoned() tests $5816+slot
// bit 3, cure clears it; level() is $57BA's low nibble, at most 8, and sets
// max HP to 30 x level; flag(npc, n) is bit n of $58C8+npc; karma is zero
// page $09 and the quest flag $0B, saved with the rest of $02-$21.

import { chunkContents, type Ucsv } from "../container/ucsv.ts";
import {
  Doc, u6SaveArea, u8, u16, table,
  type Field, type GameView, type RecordDef, type Enc, type Area, type Section, type TableRow,
  type Writer, type Warning, type Choice, type Action,
} from "./model.ts";
import { OBJECTS, NPCS, STACKS as STACK_TYPES } from "./u6names.ts";
import { ORIGINAL_SAVE_AREA } from "./u6original.ts";

const NOTES = "U6-save-game.md";
const T4 = "the Talk overlay (T001's cheat menu)";
const BASE = 0x5400;
const bcd1: Enc = { t: "bcd", n: 1 };

function s(id: string, label: string, addr: number, enc: Enc, extra: Partial<Field> = {}): Field {
  return { id, label, area: "save", at: addr - BASE, enc, conf: "reference", src: NOTES, ...extra };
}

/** The named characters' name fields, from the offset table at $577D:
 *  each name runs to the next one's offset (the last to $576E). */
function names(a: Area): (Field | null)[] {
  const out: (Field | null)[] = [];
  for (let k = 0; k < 15; k++) {
    const t = 0x577d - BASE + k;
    if (!a.has(t)) { out.push(null); continue; }
    const off = a.get(t);
    const next = k < 14 && a.has(t + 1) ? a.get(t + 1) : 0x6e;
    const n = Math.max(1, Math.min(next, 0x6e) - off);
    out.push(s(`c${k}.name`, "Name", 0x5700 + off, { t: "text", n, cs: "screen" },
      { conf: "verified", src: "launcher page and transfer", note: n > 1 ? `room for ${n - 1} letters` : undefined }));
  }
  return out;
}

// $5816 + stat slot: the game sets each with a message ("paralyzed!" at
// game $3B63, "poisoned!" $3BA7), a field sets sleep ($3C01), and the hourly
// round ($0645-$06DE) wears protection off, wakes and frees at random, and
// takes a hit point from the poisoned who are not protected.
const CONDITION: [string, string, number, Partial<Field>][] = [
  ["poisoned", "Poisoned", 0x08, { conf: "verified", src: `${T4}: poisoned() tests it, cure clears it; game $3BA7 sets it with "poisoned!"` }],
  ["paralysed", "Paralysed", 0x02, { conf: "verified", src: `game $3B63 sets it with "paralyzed!" (a web); the hourly round frees at random` }],
  ["asleep", "Asleep", 0x04, { conf: "verified", src: "game $3C01 sets it (a sleep field), the hourly round wakes at random" }],
  ["protected", "Protected", 0x01, { conf: "verified", src: "game: no poison, sleep or paralysis while it is set; the hourly round wears it off",
    note: "named from what it does (the spell's name is inferred)" }],
];

// what "heal and cure" clears: poisoned, asleep, paralysed (T001's cure clears poison only)
const AILING = 0x08 | 0x04 | 0x02;

/** Character k's hit points to the maximum and the ailments cleared, if it needs it. */
function heal(a: Area, k: number, w: Writer): void {
  w.setByte("save", 0x57e8 - BASE + k, a.get(0x57ff - BASE + k));
  w.setByte("save", 0x5816 - BASE + k, a.get(0x5816 - BASE + k) & ~AILING);
}
const needsHeal = (a: Area, k: number) =>
  a.get(0x57e8 - BASE + k) !== a.get(0x57ff - BASE + k) || (a.get(0x5816 - BASE + k) & AILING) !== 0;

function character(k: number, name: Field | null, a: Area): RecordDef {
  const st = (id: string, label: string, addr: number, enc: Enc, extra: Partial<Field> = {}) =>
    s(`c${k}.${id}`, label, addr + k, enc, extra);
  return {
    key: `c${k}`,
    title: d => (name && (d.value(name) as string)) || (k === 0 ? "The Avatar" : `Character ${k + 1}`),
    present: d => !name || d.has(name),
    sections: [
      { kind: "form", title: "Character", fields: [
        ...(name ? [name] : []),
        ...([["str", "Strength", 0x578c], ["dex", "Dexterity", 0x57a3], ["int", "Intelligence", 0x57d1]] as const).map(([id, label, addr]) =>
          st(id, label, addr, u8, { conf: "verified", src: `launcher's Avatar transfer; ${T4}: adds stop at 30`,
            rule: { max: 30, text: "the game raises an attribute to 30 at most" } })),
        st("level", "Level", 0x57ba, { t: "bits", mask: 0x0f }, { conf: "verified",
          src: `${T4}: level() keeps the high nibble, stops at 8 and sets max HP to 30 x level`,
          note: "the byte's low half; the shrines raise it, with max HP",
          rule: { min: 1, max: 8, text: "the game's levels are 1-8" } }),
        s(`c${k}.exp`, "Experience", 0x585b + 2 * k, u16, { conf: "verified", src: "launcher's Avatar transfer; T001's exp()",
          rule: { max: 9999, text: "the game stops at 9999" } }),
        st("hp", "Hit points", 0x57e8, u8, { conf: "verified", src: "launcher page; T001's heal copies the maximum" }),
        st("maxhp", "Maximum hit points", 0x57ff, u8, { conf: "verified", src: `launcher page; ${T4}: level() sets it`,
          rule: { min: 30, max: 240, step: 30, text: "the shrines set it to 30 x the level (1-8)" } }),
        st("mp", "Magic points", 0x5844, u8, { note: "the hourly round refills it by the level, up to a maximum it computes (2 x intelligence for the Avatar)" }),
        st("actor", "Actor number", 0x576e, u8, { readOnly: true, src: NOTES }),
      ] },
      { kind: "grid", title: "Condition", actions: [{ label: "Heal and cure",
          title: "Hit points to the maximum; not poisoned, asleep or paralysed",
          run: w => heal(a, k, w), disabled: () => needsHeal(a, k) ? null : "already well" }],
        fields: [
        ...CONDITION.map(([id, label, mask, extra]) => st(id, label, 0x5816, { t: "flag", mask }, extra)),
        st("invisible", "Invisible", 0x582d, { t: "flag", mask: 0x02 }, { conf: "verified",
          src: "game $0675: cleared unless an invisibility ring is worn; $0919 draws the figure differently" }),
        st("party", "With the party", 0x5816, { t: "flag", mask: 0x40 }, { readOnly: true, conf: "verified",
          src: `${T4}: joining sets it, leaving clears it`, note: "follows the party list (World)" }),
      ] },
    ],
  };
}

// The inventory: 32 slots for each place in the party (not stat slot), four
// arrays of 192: status, object, quantity, quality.  Slots 0-23 the pack,
// 24-31 what is worn, by the Ready overlay's table (1A T22 S17, $C92A types
// -> $C94B slots; bit 7 = both hands) and the Talk overlay (the Amulet to
// slot 24).
const WORN: [number, string][] = [[24, "Neck or cloak"], [25, "Head"], [26, "Body"], [27, "Weapon hand"],
  [28, "Shield hand"], [29, "Ring"], [30, "Ring (second)"], [31, "Feet"]];
// game $34B5: these stack; anything else is kept as quantity 1
const STACKS = new Set(STACK_TYPES);
// the Ready table: object -> slot (bit 7: both hands); the Amulet from the Talk overlay
const READY = new Map<number, number>([
  ...[1, 2, 0x0f].map(t => [t, 25] as [number, number]), ...[3, 4, 5, 6].map(t => [t, 28] as [number, number]),
  ...[7, 8, 9, 0x0a].map(t => [t, 26] as [number, number]),
  ...[0x0b, 0x0c, 0x0d, 0x0e, 0x12, 0x15, 0x16, 0x34, 0x35, 0x62, 0x54, 0x59].map(t => [t, 27] as [number, number]),
  ...[0x10, 0x11, 0x13, 0x14, 0x17].map(t => [t, 0x9b] as [number, number]),
  [0x1b, 31], [0x30, 29], [0x31, 29], [0x32, 29], [0x36, 24], [0x90, 24]]);

const dupes = new Set(OBJECTS.filter((n, k) => OBJECTS.indexOf(n) !== k));
const OBJECT: Enc = { t: "enum", values: OBJECTS.map((n, k): [number, string] =>
  [k, k === 0 ? "—" : dupes.has(n) ? `${n} ($${k.toString(16).toUpperCase()})` : n]) };
const objName = (t: number) => OBJECTS[t] ?? `object $${t.toString(16).toUpperCase()}`;
const wornName = (k: number) => WORN.find(([n]) => n === k)![1].toLowerCase();

// the four arrays of a slot: status, object, quantity, quality
const ARRAYS = [0x5400, 0x54c0, 0x5580, 0x5640];
const STATUS = 0, OBJ = 1, QTY = 2, QUAL = 3;
const READIED = 0x08;

/** The inventory of the party's places, read from and written to the save area. */
class Packs {
  readonly a: Area;
  constructor(a: Area) { this.a = a; }
  get(p: number, k: number, part: number): number { return this.a.get(ARRAYS[part] - BASE + p * 32 + k); }
  empty(p: number, k: number): boolean { return ARRAYS.every((_, j) => this.get(p, k, j) === 0); }
  /** Where an object goes in p's pack: a stack of the same kind and quality, else the first empty slot, or -1. */
  room(p: number, obj: number, qual: number): number {
    if (STACKS.has(obj))
      for (let k = 0; k < 24; k++) if (this.get(p, k, OBJ) === obj && this.get(p, k, QUAL) === qual) return k;
    for (let k = 0; k < 24; k++) if (this.get(p, k, OBJ) === 0) return k;
    return -1;
  }
  /** The worn slot an object readies to (the second ring's when the first is taken), or -1. */
  readySlot(p: number, obj: number): number {
    const r = READY.get(obj);
    if (r === undefined) return -1;
    const k = r & 0x7f;
    if (k === 29 && this.get(p, 29, OBJ) !== 0) return 30;
    return k;
  }
  /** Can the worn slot take it now: empty, and the shield hand free for two hands. */
  free(p: number, k: number, obj: number): boolean {
    return this.get(p, k, OBJ) === 0 && (!((READY.get(obj) ?? 0) & 0x80) || this.get(p, 28, OBJ) === 0);
  }
  /** Moves a slot's contents (merging into a stack), the readied bit set as worn or pack wants. */
  move(w: Writer, from: [number, number], to: [number, number]): void {
    const [p, k] = from, [q, j] = to;
    const v = ARRAYS.map((_, part) => this.get(p, k, part));
    const at = (part: number, pl: number, sl: number) => ARRAYS[part] - BASE + pl * 32 + sl;
    if (this.get(q, j, OBJ) === v[OBJ])                 // onto a stack
      w.setByte("save", at(QTY, q, j), Math.min(255, this.get(q, j, QTY) + v[QTY]));
    else {
      v[STATUS] = j >= 24 ? v[STATUS] | READIED : v[STATUS] & ~READIED;
      v.forEach((b, part) => w.setByte("save", at(part, q, j), b));
    }
    ARRAYS.forEach((_, part) => w.setByte("save", at(part, p, k), 0));
  }
}

interface Place { name: (d: Doc) => string; present: (d: Doc) => boolean }

function inventory(p: number, places: Place[], packs: Packs): RecordDef {
  const at = (arr: number, slot: number) => arr + p * 32 + slot;
  const area = packs.a;
  const src = { conf: "verified" as const, src: "game $3425 (taking an object: type, quantity, quality, status); the Talk overlay's give/take" };
  const slot = (k: number): TableRow => {
    const qty = s(`inv${p}.${k}.qty`, "Quantity", at(0x5580, k), u8, src);
    const qual = s(`inv${p}.${k}.qual`, "Quality", at(0x5640, k), u8, { ...src, note: "a key's number, a potion's kind ..." });
    const stat = s(`inv${p}.${k}.status`, "Status", at(0x5400, k), u8, { note: "the object's status byte: $08 readied (worn), $80 a lit torch (game $3F04)" });
    const obj = s(`inv${p}.${k}.obj`, "Object", at(0x54c0, k), OBJECT, {
      ...src, src: `${src.src}; names from 1A track 35`,
      also: (v, w) => {       // an emptied slot is all zeros; a filled one holds one at least, worn things readied
        if (v === 0) [qty, qual, stat].forEach(f => w.set(f, 0));
        else {
          if (area.get(qty.at) === 0) w.set(qty, 1);
          if (k >= 24 && area.get(stat.at) === 0) w.set(stat, 0x18);
        }
      } });
    const worn = WORN.find(([n]) => n === k);
    const menu = (d: Doc): Choice[] => {
      const t = packs.get(p, k, OBJ);
      if (t === 0) return [];
      const out: Choice[] = [];
      const room = packs.room(p, t, packs.get(p, k, QUAL));
      if (k >= 24) out.push({ label: "Take it off (to the pack)", run: w => packs.move(w, [p, k], [p, room]),
        disabled: room < 0 ? "the pack is full" : null });
      else {
        const j = packs.readySlot(p, t);
        if (j >= 0) out.push({ label: `Ready it (${wornName(j)})`, run: w => packs.move(w, [p, k], [p, j]),
          disabled: packs.free(p, j, t) ? null : `the ${wornName(j)} is taken` });
      }
      places.forEach((pl, q) => {
        if (q === p || !pl.present(d)) return;
        const r = packs.room(q, t, packs.get(p, k, QUAL));
        out.push({ label: `Give to ${pl.name(d)}`, run: w => packs.move(w, [p, k], [q, r]),
          disabled: r < 0 ? `${pl.name(d)}'s pack is full` : null });
      });
      return out;
    };
    return { label: worn ? worn[1] : `${k + 1}`, cells: [obj, qty, qual, stat], empty: () => packs.empty(p, k), menu };
  };
  const cols = ["Object", "Quantity", "Quality", "Status"];
  const firstFree = () => { for (let k = 0; k < 24; k++) if (packs.get(p, k, OBJ) === 0) return k; return -1; };
  const add: Action = { label: "Add an object", title: "Pick an object for the first empty pack slot",
    focus: () => firstFree() < 0 ? null : `inv${p}.${firstFree()}.obj`, disabled: () => firstFree() < 0 ? "the pack is full" : null };
  return {
    key: `inv${p}`,
    title: d => places[p].name(d),
    present: d => places[p].present(d),
    badge: () => {
      let pack = 0, worn = 0;
      for (let k = 0; k < 32; k++) if (packs.get(p, k, OBJ) !== 0) k < 24 ? pack++ : worn++;
      return pack + worn ? { text: String(pack + worn), title: `${pack} in the pack, ${worn} worn` } : null;
    },
    sections: [
      table("Worn", cols, WORN.map(([k]) => slot(k)),
        "Where the Ready command puts each kind. An object chosen for an empty slot gets status $18 (readied), as the game leaves worn things."),
      table("Pack", cols, Array.from({ length: 24 }, (_, k) => slot(k)),
        "An object chosen for an empty slot gets quantity 1; only arrows, bolts, reagents, food, gold, torches and the like stack.", [add]),
    ],
  };
}

const CIRCLES = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"];
// T001's "Hocus pocus" tables (offsets 1736 and 1800): spell circle * 8 + i is bit i of flag 203 + circle
const SPELLS: string[][] = [
  ["Create Food", "Dispel Magic", "Harm", "Heal", "Help", "Light"],
  ["Infravision", "Magic Arrow", "Poison", "Sleep", "Telekinesis", "Unlock Magic"],
  ["Curse", "Dispel Field", "Fireball", "Great Light", "Magic Lock", "Mass Sleep", "Protection"],
  ["Conjure", "Disable", "Fire Field", "Great Heal", "Locate", "Mass Dispel", "Sleep Field", "Wind Change"],
  ["Energy Field", "Explosion", "Invisibility", "Lightning", "Paralyze", "X-ray"],
  ["Charm", "Flame Wind", "Hail Storm", "Mass Protect", "Poison Wind", "Web"],
  ["Chain Bolt", "Energy Wind", "Gate Travel", "Kill", "Mass Curse", "Mass Invisible", "Wing Strike"],
  ["Armageddon", "Death Wind", "Mass Charm", "Mass Kill", "Resurrect", "Summon", "Time Stop", "Tremor"],
];

const FLAGS = 0x58c8;     // + NPC number: eight flags each
function person(n: number): RecordDef {
  const src = { conf: "verified" as const, src: `${T4}: flag(npc, n) is bit n of $58C8 + npc` };
  return {
    key: `npc${n}`,
    title: () => `${n}. ${NPCS[n]}`,
    sections: [{ kind: "grid", title: "Flags", bulk: false, note: "What flags 1-7 mean is up to each conversation (the cheat menu calls them H, 2-7).",
      fields: [
        s(`npc${n}.met`, "Met", FLAGS + n, { t: "flag", mask: 1 }, { ...src,
          src: `${src.src}; the Talk overlay ($CB8B) uses the name instead of the description once it is set` }),
        ...[1, 2, 3, 4, 5, 6, 7].map(b => s(`npc${n}.f${b}`, `Flag ${b}`, FLAGS + n, { t: "flag", mask: 1 << b }, src)),
      ] }],
  };
}

export function view(save: Ucsv): GameView {
  const area = u6SaveArea(save, ORIGINAL_SAVE_AREA);
  const doc = new Doc([area]);
  const nameFields = names(area);
  const records = Array.from({ length: 15 }, (_, k) => character(k, nameFields[k], area));
  const size = s("size", "Party size - 1", 0x588c, u8, { max: 5, readOnly: true, conf: "verified", src: "launcher page" });
  const members = [0, 1, 2, 3, 4, 5].map(k => s(`party.${k}`, `Party member ${k + 1} (actor)`, 0x588d + k, u8,
    { readOnly: true, conf: "verified", src: "launcher page" }));
  /** The name of the character at a party place: actor -> stat slot -> name. */
  const memberName = (p: number) => (d: Doc): string | null => {
    const actor = d.value(members[p]);
    if (typeof actor !== "number") return null;
    for (let k = 0; k < 15; k++) {
      const f = s("", "", 0x576e + k, u8);
      if (d.value(f) === actor) return (nameFields[k] && d.value(nameFields[k] as Field) as string) || (k === 0 ? "The Avatar" : null);
    }
    return NPCS[actor] ?? null;
  };
  const places: Place[] = [0, 1, 2, 3, 4, 5].map(p => ({
    name: d => memberName(p)(d) ?? `Party place ${p + 1}`,
    present: d => { const n = d.value(size); return typeof n === "number" && p <= n; },
  }));
  const packs = new Packs(area);
  const inv = [0, 1, 2, 3, 4, 5].map(p => inventory(p, places, packs));
  const named = [...Array(15).keys()].filter(k => nameFields[k] && doc.has(nameFields[k] as Field));
  const spellFlags = SPELLS.flatMap((names, c) => names.map((_, i) => [FLAGS + 203 + c - BASE, 1 << i] as const));
  const present = new Set(save.records.flatMap(r => r.kind === "sector" ? [r.sector] : []));
  const missing = [...Array(12).keys()].map(k => k + 9).filter(sc => !present.has(sc));
  const files = save.records.flatMap(r => r.kind === "file" ? [r] : []);
  const remarks: string[] = [];
  if (missing.length)
    remarks.push(`Save-area sector${missing.length > 1 ? `s ${missing.join(", ")} are` : ` ${missing[0]} is`} not in the file: `
      + `the game has ${missing.length > 1 ? "them" : "it"} as on the original Surface disk, which is what is shown; `
      + `an edit there adds ${missing.length > 1 ? "the sector" : "it"} to the file.`);
  remarks.push(`${files.length} chunk file${files.length === 1 ? "" : "s"} rewritten by the game: `
    + files.map(f => `${f.name} (${chunkContents(f).length} bytes)`).join(", ")
    + ". They hold the world's objects and are kept as they are.");
  const clock = { conf: "verified" as const, src: "game $0525: the clock counts in BCD, minutes to 60, hours to 24, days to 29, months to 13" };
  const zp = (n: number) => 0x5877 + n;     // zero page $02-$21 is saved at $5879-$5898
  const spells: Section[] = SPELLS.map((names, c) => ({ kind: "grid", title: `${CIRCLES[c]} circle`,
    note: c ? undefined : "Known spells (the cheat menu's Hocus pocus): the C64 keeps one spellbook for the party.",
    fields: names.map((n, i) => s(`spell.${c}.${i}`, n, FLAGS + 203 + c, { t: "flag", mask: 1 << i }, {
      conf: "verified", src: "T001's Hocus pocus (flag 203 + circle); the spellbook overlay (1A T3 S15) reads $5993 + circle bit by bit" })) }));
  return {
    game: 6, title: "Ultima VI", doc,
    tabs: [
      { title: "Party", sections: [{ kind: "records", title: "Named characters", records,
        note: "Stat slot 0 is the Avatar, 1-14 the companions in name order." }],
        actions: [{ label: "Heal and cure everyone", title: "Every named character's hit points to the maximum; nobody poisoned, asleep or paralysed",
          run: w => named.forEach(k => heal(area, k, w)),
          disabled: () => named.some(k => needsHeal(area, k)) ? null : "everyone is well" }] },
      { title: "Inventory", sections: [{ kind: "records", title: "Party", records: inv,
        note: "Each place in the party carries its own; the World tab says who is where." }] },
      { title: "Spells", sections: spells, actions: [
        { label: "Learn every spell", run: w => spellFlags.forEach(([at, bit]) => w.setByte("save", at, area.get(at) | bit)),
          disabled: () => spellFlags.every(([at, bit]) => area.get(at) & bit) ? "every spell is known" : null },
        { label: "Forget every spell", run: w => spellFlags.forEach(([at, bit]) => w.setByte("save", at, area.get(at) & ~bit)),
          disabled: () => spellFlags.some(([at, bit]) => area.get(at) & bit) ? null : "no spell is known" },
      ] },
      { title: "People", sections: [{ kind: "records", title: "Everyone who talks",
        records: Array.from({ length: 202 }, (_, k) => person(k + 1)),
        note: "Numbered as the game numbers them (the conversations, the actors)." }] },
      { title: "World", sections: [
        { kind: "form", title: "Party", fields: [
          s("sex", "The Avatar's sex", 0x588b, { t: "enum", values: [[0, "Male"], [1, "Female"]] }, { conf: "verified", src: "create $028B stores the answer in zero page $14" }),
          size, ...members,
          s("karma", "Karma", zp(0x09), u8, { conf: "verified", src: `${T4}: karma is zero page $09, +/- stops at 0 and 99`,
            rule: { max: 99, text: "the game keeps karma at 99 at most" } }),
          s("quest", "Quest flag", zp(0x0b), u8, { conf: "verified", src: `${T4}: the cheat menu's Questflag is zero page $0B` }),
        ] },
        { kind: "form", title: "Time", fields: [
          s("hour", "Hour", zp(0x04), bcd1, { ...clock, max: 23 }),
          s("minute", "Minute", zp(0x03), bcd1, { ...clock, max: 59 }),
          s("day", "Day", zp(0x05), bcd1, { ...clock, min: 1, max: 28 }),
          s("month", "Month", zp(0x06), bcd1, { ...clock, min: 1, max: 12 }),
          s("year", "Year", zp(0x07), { t: "bcd", n: 2, le: true }, { ...clock, note: "the game starts on 4 July 161" }),
        ] },
        { kind: "form", title: "Where the Avatar is", note: "Shown only: moving the party needs every member's position and the view's origin to agree.",
          fields: [
            s("ax", "X (low byte)", 0x5b26, u8, { readOnly: true }), s("axh", "X (high byte)", 0x5bea, u8, { readOnly: true }),
            s("ay", "Y (low byte)", 0x5cae, u8, { readOnly: true }), s("ayh", "Y (high byte)", 0x5d72, u8, { readOnly: true }),
            s("az", "Level (0 = the surface)", 0x5e36, u8, { readOnly: true }),
          ] },
      ] },
    ],
    readOnly: null,
    remarks,
    warnings() {
      const out: Warning[] = [];
      for (let k = 0; k < 15; k++) {
        const hpf = s("", "", 0x57e8 + k, u8);
        const hp = doc.value(hpf), mx = doc.value(s("", "", 0x57ff + k, u8));
        const n = nameFields[k] ? doc.value(nameFields[k] as Field) : undefined;
        if (typeof hp === "number" && typeof mx === "number" && hp > mx && n)
          out.push({ text: `${n} has more hit points (${hp}) than the maximum (${mx}).`, id: `c${k}.hp`,
            fix: { label: `Set to ${mx}`, run: w => w.set(hpf, mx) } });
      }
      const n = doc.value(size);
      for (let p = 0; typeof n === "number" && p <= Math.min(n, 5); p++) {
        const who = places[p].name(doc);
        for (let k = 0; k < 32; k++) {
          const t = packs.get(p, k, OBJ), q = packs.get(p, k, QTY);
          if (!doc.has(s("", "", 0x54c0 + p * 32 + k, u8)) || t === 0) continue;
          const where = k < 24 ? `pack slot ${k + 1}` : wornName(k);
          const one: Choice = { label: "Set to 1", run: w => w.setByte("save", 0x5580 - BASE + p * 32 + k, 1) };
          if (q === 0) out.push({ text: `${who}'s ${objName(t)} (${where}) has quantity 0.`, id: `inv${p}.${k}.qty`, fix: one });
          else if (q > 1 && !STACKS.has(t))
            out.push({ text: `${who} has ${q} of ${objName(t)} (${where}): it does not stack, the game keeps 1 a slot.`, id: `inv${p}.${k}.qty`, fix: one });
          if (k >= 24) {
            const r = READY.get(t), slot = r === undefined ? undefined : r & 0x7f;
            const fits = slot === k || (slot === 27 && !(r! & 0x80) && k === 28) || (slot === 29 && k === 30);
            if (fits) continue;
            const j = slot === undefined ? -1 : packs.readySlot(p, t);
            const room = packs.room(p, t, packs.get(p, k, QUAL));
            const fix: Choice | undefined = j >= 0 && packs.free(p, j, t) ? { label: `Move it to the ${wornName(j)}`, run: w => packs.move(w, [p, k], [p, j]) }
              : room >= 0 ? { label: "Move it to the pack", run: w => packs.move(w, [p, k], [p, room]) } : undefined;
            out.push({ text: `${who} wears ${objName(t)} on the ${where}: `
              + (slot === undefined ? "the Ready command does not ready it." : `the Ready command puts it on the ${wornName(slot)}.`),
              id: `inv${p}.${k}.obj`, fix });
          }
        }
      }
      return out;
    },
  };
}
