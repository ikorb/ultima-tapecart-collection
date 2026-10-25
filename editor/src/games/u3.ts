// Ultima III: the Scenario disk's SOSA (Sosaria's map), SOSM (its
// monsters), ROST (20 characters, 64 bytes each), PLRS (the party's four
// copies) and PRTY (the party).
//
// Sources: C64UltimaEditor's notes (zoggins: the 64-byte record and PRTY),
// checked against its played disk; the collection's own research (the
// launcher page, ultima/games/u3/build.py: torches +$0F and gems +$25, u3maps.py
// and u3talk.py: SOSA and SOSM).  HP is +$1A/+$1B and its maximum
// +$1C/+$1D: ULT3's heal at $6FCF adds to the first and caps it at the
// second (C64UltimaEditor's code has them the other way round).
//
// The roster as BOOT keeps it: a place is used while its name's first byte
// is not zero.  Forming a party sets each member's +$10 to $FF ($17A1) and
// copies the records into PLRS (SUBS $49AA); dispersing it copies PLRS back
// and clears +$10 ($18AF).  ULT3 never writes ROST, so a member's roster
// record is as it was when the party was formed.  Terminating a character
// zeroes its 64 bytes ($1980) and is refused while +$10 is set ($195A).
// Nothing in a record names its place (PRTY +6..+9 do, from 1).

import type { Ucsv } from "../container/ucsv.ts";
import {
  Doc, slotArea, copyBytes, bcd1, bcd2, bcd4, u8, enumOf, counts,
  type Field, type GameView, type RecordDef, type Enc, type Warning, type Action, type Choice,
} from "./model.ts";

const ZOG = "C64UltimaEditor notes";
// seen on the game's Ztats with a distinct value in each field (tools/vice/editor_game_check.py)
const ZTATS = "U3's Ztats";
// ULT3 $6B43-$6C27 prints them bit by bit from the record's +$0E
const CARDS: [string, number][] = [["Card of Death", 0x08], ["Card of Sol", 0x02], ["Card of Love", 0x01],
  ["Card of Moons", 0x04], ["Mark of Force", 0x10], ["Mark of Fire", 0x20], ["Mark of Snake", 0x40], ["Mark of Kings", 0x80]];

export const WEAPONS = ["Hands", "Dagger", "Mace", "Sling", "Axe", "Bow", "Sword", "Two-handed sword",
  "+2 axe", "+2 bow", "+2 sword", "Gloves", "+4 axe", "+4 bow", "+4 sword", "Exotic"];
export const ARMOUR = ["Skin", "Cloth", "Leather", "Chain", "Plate", "+2 chain", "+2 plate", "Exotic"];
const STATUS: Enc = { t: "enum", values: [[0xc7, "Good"], [0xd0, "Poisoned"], [0xc4, "Dead"], [0xc1, "Ashes"]] };
const RACE: Enc = { t: "enum", values: [[0xc8, "Human"], [0xc5, "Elf"], [0xc4, "Dwarf"], [0xc2, "Bobbit"], [0xc6, "Fuzzy"]] };
const CLASS: Enc = { t: "enum", values: [[0xc6, "Fighter"], [0xc3, "Cleric"], [0xd7, "Wizard"], [0xd4, "Thief"],
  [0xd0, "Paladin"], [0xc2, "Barbarian"], [0xcc, "Lark"], [0xc9, "Illusionist"], [0xc4, "Druid"],
  [0xc1, "Alchemist"], [0xd2, "Ranger"]] };
const SEX: Enc = { t: "enum", values: [[0xcd, "Male"], [0xc6, "Female"], [0xcf, "Other"]] };
const GOOD = 0xc7, POISONED = 0xd0;

/** Hit points to the maximum and poison cured for every named character of an area (the dead stay dead). */
function healAll(doc: Doc, area: string, n: number, who: string): Action {
  const fld = (k: number, at: number, enc: Enc): Field => ({ id: "", label: "", area, at: k * 64 + at, enc, conf: "verified", src: "" });
  const ill = (k: number) => !!doc.value(fld(k, 0, { t: "text", n: 14, cs: "high" })) && doc.value(fld(k, 0x11, u8)) !== 0xc4 && doc.value(fld(k, 0x11, u8)) !== 0xc1
    && (doc.value(fld(k, 0x1a, bcd2)) !== doc.value(fld(k, 0x1c, bcd2)) || doc.value(fld(k, 0x11, u8)) === POISONED);
  return { label: `Heal and cure ${who}`, title: "Hit points to the maximum, poison cured; the dead and ashes stay as they are",
    disabled: () => [...Array(n).keys()].some(ill) ? null : `${who} ${who === "everyone" ? "is" : "is all"} well`,
    run: w => { for (let k = 0; k < n; k++) if (ill(k)) {
      const a = doc.area(area);
      w.setByte(area, k * 64 + 0x1a, a.get(k * 64 + 0x1c));
      w.setByte(area, k * 64 + 0x1b, a.get(k * 64 + 0x1d));
      if (a.get(k * 64 + 0x11) === POISONED) w.setByte(area, k * 64 + 0x11, GOOD);
    } } };
}

const REC = 64, IN_PARTY = 0x10;
const named = (d: Doc, area: string, k: number) => d.area(area).get(k * REC) !== 0;
const inParty = (d: Doc, k: number) => d.area("rost").get(k * REC + IN_PARTY) !== 0;
const nameOf = (d: Doc, area: string, k: number) =>
  d.value({ id: "", label: "", area, at: k * REC, enc: { t: "text", n: 14, cs: "high" }, conf: "verified", src: "" }) as string;

/** A roster place's own edits: another character copied into it (out of
 *  any party: +$10 cleared), and deleted as BOOT's terminate deletes. */
function rosterEdits(k: number): Pick<RecordDef, "menus" | "actions"> {
  const busy = (d: Doc) => inParty(d, k) ? "in the party: disperse it in the game first" : null;
  const from = (d: Doc, area: string, j: number, label: string): Choice => ({ label,
    disabled: busy(d) ?? (!named(d, area, j) ? "empty" : null),
    run: w => { copyBytes(w, d, [area, j * REC], ["rost", k * REC], REC); w.setByte("rost", k * REC + IN_PARTY, 0); } });
  return {
    menus: [{ label: "Copy from…", choices: d => [
      ...[0, 1, 2, 3].filter(j => j < (d.areas.get("prty")?.get(1) ?? 0)).map(j =>
        from(d, "plrs", j, `Party member ${j + 1}: ${nameOf(d, "plrs", j)} (as the game plays it)`)),
      ...Array.from({ length: 20 }, (_, j) => j).filter(j => j !== k).map(j =>
        from(d, "rost", j, `Place ${j + 1}: ${nameOf(d, "rost", j) || "empty"}`
          + (named(d, "rost", j) && inParty(d, j) ? " (in the party: as when it was formed)" : ""))),
    ] }],
    actions: [{ label: "Delete", title: "Clears the place, as the game's Terminate does",
      disabled: d => !named(d, "rost", k) ? "the place is empty" : busy(d), run: w => {
        for (let i = 0; i < REC; i++) w.setByte("rost", k * REC + i, 0);
      } }],
  };
}

function record(area: string, k: number, title: string): RecordDef {
  const o = k * 64;
  const f = (id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id: `${area}${k}.${id}`, label, area, at: o + at, enc, conf: "verified", src: ZTATS, ...extra });
  const name = f("name", "Name", 0x00, { t: "text", n: 14, cs: "high", upper: true }, { conf: "verified", src: "launcher page" });
  return {
    key: `${area}${k}`,
    title: d => (d.value(name) as string) || `${title} ${k + 1}`,
    present: d => !!d.value(name),
    ...(area === "rost" ? rosterEdits(k) : {}),
    sections: [
      { kind: "form", title: "Character", fields: [
        name,
        f("sex", "Sex", 0x18, SEX, { src: `${ZTATS}: the party panel prints the letter` }),
        f("race", "Race", 0x16, RACE, { src: `${ZTATS}: the party panel prints the letter` }),
        f("class", "Class", 0x17, CLASS, { src: `${ZTATS}: the party panel prints the letter` }),
        f("status", "Status", 0x11, STATUS, { src: "launcher page; the party panel prints the letter" }),
        ...(area === "rost" ? [f("inparty", "In the party", 0x10, { t: "nonzero", on: 0xff },
          { conf: "verified", src: "BOOT $17A1 (formed), $18BC (dispersed)", note: "kept in step with PRTY's list by the game", readOnly: true })] : []),
      ] },
      { kind: "form", title: "Attributes", fields: [
        f("str", "Strength", 0x12, bcd1), f("dex", "Dexterity", 0x13, bcd1),
        f("int", "Intelligence", 0x14, bcd1), f("wis", "Wisdom", 0x15, bcd1),
        f("mp", "Magic points", 0x19, bcd1, { src: "U3's party panel (M:)" }),
        f("hp", "Hit points", 0x1a, bcd2, { conf: "verified", src: "ULT3 $6FCF (heal, capped at the maximum)" }),
        f("maxhp", "Maximum hit points", 0x1c, bcd2, { conf: "verified", src: "ULT3 $6FCF" }),
        f("exp", "Experience", 0x1e, bcd2, { note: "the level is experience / 100 + 1" }),
      ] },
      { kind: "form", title: "Supplies", fields: [
        f("food", "Food", 0x20, bcd2, { src: "U3's party panel (F:)" }), f("gold", "Gold", 0x23, bcd2),
        f("torches", "Torches", 0x0f, bcd1, { conf: "verified", src: "ultima/games/u3/build.py (the torch patch)" }),
        f("gems", "Gems", 0x25, bcd1, { conf: "verified", src: "ultima/games/u3/build.py (the gem check)" }),
        f("keys", "Keys", 0x26, bcd1), f("powder", "Powder", 0x27, bcd1),
      ] },
      { kind: "grid", title: "Cards and marks", fields: CARDS.map(([n, bit], j) =>
        f(`card${j}`, n, 0x0e, { t: "flag", mask: bit }, { src: "ULT3 $6B43-$6C27 (Ztats)" })) },
      { kind: "form", title: "Equipped", fields: [
        f("armour", "Armour", 0x28, enumOf(ARMOUR)), f("weapon", "Weapon", 0x30, enumOf(WEAPONS)),
      ] },
      { kind: "grid", title: "Weapons", fields: counts(area, o + 0x30, ["", ...WEAPONS.slice(1)], bcd1, { conf: "verified", src: ZTATS }, `${area}${k}.weapons`) },
      { kind: "grid", title: "Armour", fields: counts(area, o + 0x28, ["", ...ARMOUR.slice(1)], bcd1, { conf: "verified", src: ZTATS }, `${area}${k}.armours`) },
    ],
  };
}

export function view(save: Ucsv): GameView {
  const doc = new Doc([
    slotArea(save, "plrs", "PLRS: the party's characters (at $4000)", [3], 0x4000),
    slotArea(save, "rost", "ROST: the roster (at $9500)", [2], 0x9500),
    slotArea(save, "prty", "PRTY: the party (at $CD00)", [4], 0xcd00),
    slotArea(save, "sosm", "SOSM: Sosaria's monsters (at $4F00)", [1], 0x4f00),
    slotArea(save, "sosa", "SOSA: Sosaria's map (64 x 64, a tile x 4 a byte)", [0], 0x1000),
  ]);
  const pr = (id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id, label, area: "prty", at, enc, conf: "reference", src: ZOG, ...extra });
  return {
    game: 3, title: "Ultima III", doc,
    tabs: [
      { title: "Party", sections: [{ kind: "records", title: "The party (PLRS)",
        note: "The game plays with these copies; the roster below holds every character.",
        records: [0, 1, 2, 3].map(k => record("plrs", k, "Party member")) }],
        actions: [healAll(doc, "plrs", 4, "the party")] },
      { title: "Roster", sections: [{ kind: "records", title: "The roster (ROST)",
        records: Array.from({ length: 20 }, (_, k) => record("rost", k, "Roster place")) }],
        actions: [healAll(doc, "rost", 20, "everyone")] },
      { title: "World", sections: [
        { kind: "form", title: "The party", fields: [
          pr("size", "Party size", 0x01, u8, { readOnly: true, conf: "verified", src: "launcher page" }),
          ...[0, 1, 2, 3].map(k => pr(`member${k}`, `Member ${k + 1} (roster place, from 1)`, 0x06 + k, u8,
            { readOnly: true, note: k === 0 ? "checked against C64UltimaEditor's played disk" : undefined })),
          pr("x", "X", 0x03, u8, { max: 63, conf: "verified", src: "ULT3: Q copies $F7/$F8 there ($6483), the load puts them back ($6D61)",
            note: "where the party is (on Sosaria, or in the town it is in)" }),
          pr("y", "Y", 0x04, u8, { max: 63, conf: "verified", src: "ULT3: Q copies $F7/$F8 there ($6483), the load puts them back ($6D61)" }),
          pr("moves", "Moves", 0x0a, bcd4, { conf: "verified", src: "ULT3 $648B (Q prints them)" }),
        ] },
      ] },
    ],
    readOnly: null,
    remarks: [],
    warnings() {
      const out: Warning[] = [];
      for (const area of ["plrs", "rost"])
        for (let k = 0; k < (area === "plrs" ? 4 : 20); k++) {
          const fld = (at: number, enc: Enc): Field => ({ id: "", label: "", area, at: k * 64 + at, enc, conf: "reference", src: "" });
          const n = doc.value(fld(0, { t: "text", n: 14, cs: "high" }));
          if (!n) continue;
          const hp = doc.value(fld(0x1a, bcd2)) as number, mx = doc.value(fld(0x1c, bcd2)) as number;
          if (hp > mx) out.push({ text: `${n} has more hit points (${hp}) than the maximum (${mx}).`, id: `${area}${k}.hp`,
            fix: { label: `Set to ${mx}`, run: w => w.set(fld(0x1a, bcd2), mx) } });
        }
      return out;
    },
  };
}
