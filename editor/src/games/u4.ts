// Ultima IV: five blocks of the Britannia disk (271-275).  273-274 are
// chunk $80 at $AA00: eight 32-byte party records, then the inventory at
// +$100; 275 is zero page $10-$2F; 271/272 the object tables.
//
// Sources: the Remastered kit's own editor (4/u4remastered/src/editor:
// savegame.h, draw.c, stat.c), MagerValp's, which edits exactly these
// blocks; the U6 transfer's research (docs/developer/u6.md, the Avatar from Ultima IV
// or V: U4 block 273's record), the launcher page (asm/page.s) and the
// kit's symbol files (zero page).

import type { Ucsv } from "../container/ucsv.ts";
import {
  Doc, slotArea, bcd1, bcd2, bcd4, u8, enumOf, counts,
  type Field, type GameView, type Section, type RecordDef, type Enc, type Warning, type Action, type Writer,
} from "./model.ts";

const KIT = "Remastered editor";
// seen on the game's Ztats pages (F5/F7) with a distinct value in each field (tools/vice/editor_game_check.py)
const ZTATS = "U4's Ztats";
const ATTR = { max: 50, text: "the game raises an attribute to 50 at most" };
const MAXHP = { min: 100, max: 800, step: 100,
  text: "the game keeps it at 100 x the level (1-8), and may set it back -- after camping, say" };
const XFER = "U6 transfer research";

export const CLASSES = ["Mage", "Bard", "Fighter", "Druid", "Tinker", "Paladin", "Ranger", "Shepherd"];
export const WEAPONS = ["Hands", "Staff", "Dagger", "Sling", "Mace", "Axe", "Sword", "Bow", "Crossbow",
  "Flaming oil", "Halberd", "Magic axe", "Magic sword", "Magic bow", "Magic wand", "Mystic sword"];
export const ARMOUR = ["Skin", "Cloth", "Leather", "Chain mail", "Plate mail", "Magic chain",
  "Magic plate", "Mystic robe"];
export const REAGENTS = ["Sulfurous ash", "Ginseng", "Garlic", "Spider silk", "Blood moss",
  "Black pearl", "Nightshade", "Mandrake root"];
export const VIRTUES = ["Honesty", "Compassion", "Valor", "Justice", "Sacrifice", "Honor",
  "Spirituality", "Humility"];
export const SPELLS = ["Awaken", "Blink", "Cure", "Dispel", "Energy field", "Fireball", "Gate travel",
  "Heal", "Iceball", "Jinx", "Kill", "Light", "Magic missile", "Negate", "Open", "Protection",
  "Quickness", "Resurrect", "Sleep", "Tremor", "Undead", "View", "Winds", "X-it", "Y-up", "Z-down"];
const STONES = ["Blue", "Yellow", "Red", "Green", "Orange", "Purple", "White", "Black"];

const SEX: Enc = { t: "enum", values: [[0x5c, "Male"], [0x7b, "Female"]] };
const STATUS: Enc = { t: "enum", values: [[0xc7, "Good"], [0xd0, "Poisoned"], [0xd3, "Sleeping"], [0xc4, "Dead"]] };
const TRANSPORT: Enc = { t: "enum", values: [
  [0x1f, "On foot"], [0x14, "Horse (facing west)"], [0x15, "Horse (facing east)"],
  [0x10, "Ship (facing west)"], [0x11, "Ship (facing north)"], [0x12, "Ship (facing east)"],
  [0x13, "Ship (facing south)"], [0x18, "Balloon"]] };
const MODE: Enc = { t: "enum", values: [[1, "Britannia"], [2, "A town or castle"], [3, "A dungeon"]] };

function record(i: number): RecordDef {
  const at = i * 32;
  const f = (id: string, label: string, off: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id: `p${i}.${id}`, label, area: "party", at: at + off, enc, conf: "reference", src: KIT, ...extra });
  const clazz = f("class", "Class", 0x11, enumOf(CLASSES), {
    conf: "verified", src: XFER,
    also: (v, w) => w.setByte("party", at + 0x17, 0x80 >> Number(v)),     // the class mask, kept in step
  });
  return {
    key: `p${i}`,
    title: d => (d.value(f("name", "", 0, { t: "text", n: 16, cs: "high" })) as string) || `Place ${i + 1}`,
    present: d => i < Number(d.value(PARTY_SIZE) ?? 0),
    sections: [
      { kind: "form", title: "Character", fields: [
        f("name", "Name", 0x00, { t: "text", n: 16, cs: "high", upper: true }, { conf: "verified", src: "launcher page" }),
        f("sex", "Sex", 0x10, SEX, { conf: "verified", src: XFER }),
        clazz,
        f("status", "Status", 0x12, STATUS, { conf: "verified", src: "launcher page" }),
      ] },
      { kind: "form", title: "Attributes", fields: [
        f("str", "Strength", 0x13, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        f("dex", "Dexterity", 0x14, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        f("int", "Intelligence", 0x15, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        f("mp", "Magic points", 0x16, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}` }),
        f("hp", "Hit points", 0x18, bcd2, { conf: "verified", src: "launcher page" }),
        f("maxhp", "Maximum hit points", 0x1a, bcd2, { conf: "verified", src: `launcher page; ${XFER}; ${ZTATS}`,
          rule: MAXHP, note: "Ztats shows its first two digits as the level (LV)" }),
        f("exp", "Experience", 0x1c, bcd2, { conf: "verified", src: XFER }),
      ] },
      { kind: "form", title: "Equipped", fields: [
        f("weapon", "Weapon", 0x1e, enumOf(WEAPONS), { conf: "verified", src: ZTATS }),
        f("armour", "Armour", 0x1f, enumOf(ARMOUR), { conf: "verified", src: ZTATS }),
      ] },
    ],
  };
}

const PARTY_SIZE: Field = { id: "size", label: "Party size", area: "state", at: 0x0f, enc: u8, min: 1, max: 8,
  conf: "verified", src: "launcher page (0 = no game)" };

function inv(id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field {
  return { id, label, area: "party", at: 0x100 + at, enc, conf: "verified", src: ZTATS, ...extra };
}

const GOOD = 0xc7, DEAD = 0xc4;

/** Food and gold to 9999, torches, gems and keys to 99. */
function fillUp(doc: Doc, fields: Field[]): Action {
  const full = (f: Field) => f.enc.t === "bcd" ? 10 ** (2 * f.enc.n) - 1 : 0;
  return { label: "Fill up", title: fields.map(f => `${f.label} ${full(f)}`).join(", "),
    disabled: () => fields.every(f => doc.value(f) === full(f)) ? "all full" : null,
    run: (w: Writer) => fields.forEach(f => w.set(f, full(f))) };
}

export function view(save: Ucsv): GameView {
  const doc = new Doc([
    slotArea(save, "party", "Party and inventory (blocks 273-274, at $AA00)", [2, 3], 0xaa00),
    slotArea(save, "state", "Game state (block 275: zero page $10-$2F)", [4], 0x10),
    slotArea(save, "objB", "Britannia's objects while inside (block 271)", [0], 0xac00),
    slotArea(save, "obj", "Objects of the current map (block 272)", [1], 0xac00),
  ]);
  const st = (id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id, label, area: "state", at, enc, conf: "reference", src: "Remastered kit's symbols", ...extra });
  const records = Array.from({ length: 8 }, (_, i) => record(i));
  const inventory: Section[] = [
    { kind: "form", title: "Supplies", actions: [] as Action[], fields: [
      inv("food", "Food", 0x10, bcd2, { note: "whole rations; the hundredths are the byte after" }),   // F: on screen
      inv("gold", "Gold", 0x13, bcd2),
      inv("torches", "Torches", 0x08, bcd1),
      inv("gems", "Gems", 0x09, bcd1),
      inv("keys", "Keys", 0x0a, bcd1),
      inv("sextant", "Sextant", 0x0b, { t: "nonzero", on: 1 }),
    ] },
    { kind: "grid", title: "Virtues", fields: counts("party", 0x100, VIRTUES, bcd1,
        { conf: "reference", src: KIT, max: 99 }, "virtue") },
    { kind: "grid", title: "Runes", fields: VIRTUES.map((v, k) => inv(`rune.${k}`, v, 0x0d, { t: "flag", mask: 0x80 >> k })) },
    { kind: "grid", title: "Stones", fields: STONES.map((s, k) => inv(`stone.${k}`, `${s} (${VIRTUES[k]})`, 0x0c, { t: "flag", mask: 0x80 >> k })) },
    { kind: "grid", title: "Quest items", fields: [
      inv("bell", "Bell of Courage", 0x0e, { t: "flag", mask: 4 }),
      inv("book", "Book of Truth", 0x0e, { t: "flag", mask: 2 }),
      inv("candle", "Candle of Love", 0x0e, { t: "flag", mask: 1 }),
      inv("keyT", "Key part of Truth", 0x0f, { t: "flag", mask: 4 }),
      inv("keyL", "Key part of Love", 0x0f, { t: "flag", mask: 2 }),
      inv("keyC", "Key part of Courage", 0x0f, { t: "flag", mask: 1 }),
      inv("horn", "Silver horn", 0x15, { t: "nonzero", on: 1 }),
      inv("wheel", "Wheel of H.M.S. Cape", 0x16, { t: "nonzero", on: 1 }),
      inv("skull", "Skull of Mondain", 0x17, { t: "nonzero", on: 1 }),
    ] },
    { kind: "grid", title: "Weapons", fields: counts("party", 0x120, ["", ...WEAPONS.slice(1)], bcd1, { conf: "verified", src: ZTATS }, "weapons") },
    { kind: "grid", title: "Armour", fields: counts("party", 0x118, ["", ...ARMOUR.slice(1)], bcd1, { conf: "verified", src: ZTATS }, "armours") },
    { kind: "grid", title: "Reagents", fields: counts("party", 0x138, REAGENTS, bcd1, { conf: "verified", src: ZTATS }, "reagent") },
    { kind: "grid", title: "Mixtures", note: "Ztats shows A to X; Y and Z follow",
      fields: counts("party", 0x140, SPELLS, bcd1, { conf: "verified", src: ZTATS }, "mixture") },
  ];
  const supplies = inventory[0];
  if (supplies.kind === "form") supplies.actions = [fillUp(doc, supplies.fields.filter(f => f.enc.t === "bcd"))];
  const n = () => Number(doc.value(PARTY_SIZE) ?? 0);
  const pf = (i: number, at: number, enc: Enc): Field => ({ ...PARTY_SIZE, area: "party", at: i * 32 + at, enc, min: undefined, max: undefined });
  const ill = (i: number) => doc.value(pf(i, 0x12, u8)) !== DEAD
    && (doc.value(pf(i, 0x18, bcd2)) !== doc.value(pf(i, 0x1a, bcd2)) || doc.value(pf(i, 0x12, u8)) !== GOOD);
  const heal: Action = { label: "Heal and cure the party", title: "Hit points to the maximum, status Good; the dead stay dead",
    disabled: () => [...Array(n()).keys()].some(ill) ? null : "the party is well",
    run: w => { for (let i = 0; i < n(); i++) if (ill(i)) { w.set(pf(i, 0x18, bcd2), doc.value(pf(i, 0x1a, bcd2)) as number); w.set(pf(i, 0x12, u8), GOOD); } } };
  const world: Section[] = [
    { kind: "form", title: "Where the party is", note: "Changing the place is safest on the surface (mode Britannia, location 0).",
      fields: [
        PARTY_SIZE,
        st("x", "X", 0x00, u8), st("y", "Y", 0x01, u8),
        st("mode", "Mode", 0x0b, MODE),
        st("location", "Location (0 = Britannia)", 0x0a, u8),
        st("level", "Dungeon level", 0x0c, u8),
        st("transport", "Transport", 0x0e, TRANSPORT, { src: "C64UltimaEditor notes" }),
        st("flying", "Balloon flying", 0x0d, { t: "nonzero", on: 1 }),
        st("light", "Light left (dungeon)", 0x11, u8),
        st("moves", "Moves", 0x1c, bcd4, { src: "C64UltimaEditor notes" }),
      ] },
  ];
  return {
    game: 4, title: "Ultima IV", doc,
    tabs: [
      { title: "Party", sections: [{ kind: "records", title: "Characters", records }], actions: [heal] },
      { title: "Inventory", sections: inventory },
      { title: "World", sections: world },
    ],
    readOnly: null,
    remarks: [],
    warnings() {
      const out: Warning[] = [];
      for (let i = 0; i < n(); i++) {
        const hp = doc.value(pf(i, 0x18, bcd2)) as number;
        const mx = doc.value(pf(i, 0x1a, bcd2)) as number;
        const name = doc.value(pf(i, 0, { t: "text", n: 16, cs: "high" }));
        if (hp > mx) out.push({ text: `${name || `Character ${i + 1}`} has more hit points (${hp}) than the maximum (${mx}).`, id: `p${i}.hp`,
          fix: { label: `Set to ${mx}`, run: w => w.set(pf(i, 0x18, bcd2), mx) } });
        if (!name) out.push({ text: `Party place ${i + 1} has no name, but the party size includes it.`, id: `p${i}.name` });
      }
      return out;
    },
  };
}
