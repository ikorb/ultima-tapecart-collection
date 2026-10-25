// Ultima I: RO (the four roster names, 64 bytes at $B000) and P0-P3 (one
// character each, 458 bytes at $81E2).  Offsets below are into the file's
// data, without its two-byte load address.
//
// Sources: C64UltimaEditor (zoggins; its offsets include the load address,
// so they are 2 higher), the U1 notes and the collection's own research
// (dialogue/u1talk.py, maps/u1maps.py, the launcher page).  The two bytes
// at +$82/+$83 are not a checksum: GE fills them with random numbers at
// creation ($25BA/$25C0: JSR $1670 / STA $8264, $8265) and SP copies them to
// $FC/$FD; no other absolute reference to them is in any file on the U1
// disk (searched).
//
// A seat is in use while its RO byte +0 is not zero (GE $8E29, $9592,
// $95D2).  Making a character sets it to $FF, copies the name to +3 and
// saves RO and the seat's P file (GE $9329-$9353); terminating one clears
// +0 alone and saves RO (GE $8ED9-$8EE0): the name and the P file stay, and
// the next character made there overwrites them.  Nothing in a P file
// names its seat (the seat is $C4F8, in no file).

import type { Ucsv } from "../container/ucsv.ts";
import {
  Doc, optionalSlotArea, copyBytes, u8, u16, enumOf, counts,
  type Field, type GameView, type RecordDef, type Enc, type Choice,
} from "./model.ts";

const ZOG = "C64UltimaEditor";
// seen on the game's Ztats screen with a distinct value in each field (tools/vice/editor_game_check.py)
const ZTATS = "U1's Ztats screen";

export const WEAPONS = ["Dagger", "Mace", "Axe", "Rope and spikes", "Sword", "Great sword", "Bow and arrows",
  "Amulet", "Wand", "Staff", "Triangle", "Pistol", "Light sword", "Phazor", "Blaster"];
export const ARMOUR = ["Leather armour", "Chain mail", "Plate mail", "Vacuum suit", "Reflect suit"];
export const SPELLS = ["Open", "Unlock", "Magic missile", "Steal", "Ladder down", "Ladder up", "Blink",
  "Create", "Destroy", "Kill"];
export const VEHICLES = ["Horse", "Cart", "Raft", "Frigate", "Aircar", "Shuttle"];
export const GEMS = ["Red gems", "Green gems", "Blue gems", "White gems"];
// the game's own lists (MI's name tables $777C, $78D4, $7888, $7930), index 0 included
const READY_WEAPON = enumOf(["Hands", ...WEAPONS]);
const READY_ARMOUR = enumOf(["Skin", ...ARMOUR]);
const READY_SPELL = enumOf(["Prayer", ...SPELLS]);
const RIDING = enumOf(["On foot", ...VEHICLES, "Phantom"]);
const RACES: Enc = { t: "enum", values: [[1, "Human"], [2, "Elf"], [3, "Dwarf"], [4, "Bobbit"]] };
const CLASSES: Enc = { t: "enum", values: [[1, "Fighter"], [2, "Cleric"], [3, "Wizard"], [4, "Thief"]] };
// the castle whose king keeps quest byte k (build/dialogue/u1: "castle k = ...")
const KINGS = ["The White Dragon's Castle", "The Castle of the Lost King", "The Castle of Olympus",
  "The Castle Rondorlin", "The Castle Barataria", "The Black Dragon's Castle",
  "The Castle of Lord British", "The Castle of Shamino"];

const SEAT = 16, P_LEN = 458;
const SEATS = [0, 1, 2, 3];
const inUse = (d: Doc, k: number) => d.area("ro").get(SEAT * k) !== 0;

function character(k: number): RecordDef {
  const area = `p${k}`;
  const f = (id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id: `${area}.${id}`, label, area, at, enc, conf: "reference", src: ZOG, ...extra });
  const roName: Field = { id: `ro${k}.name`, label: "Roster name", area: "ro", at: 16 * k + 3,
    enc: { t: "text", n: 13, cs: "ascii" }, conf: "verified", src: "launcher page" };
  const name = f("name", "Name", 0x4b, { t: "text", n: 13, cs: "ascii" }, {
    conf: "verified", src: "U1 notes; the roster's copy follows",
    also: (v, w) => w.set(roName, v) });
  const used: Field = { id: `ro${k}.used`, label: "Seat in use", area: "ro", at: SEAT * k, enc: { t: "nonzero", on: 0xff },
    conf: "verified", src: "GE $8E29 (a free seat), $9329 (made), $8ED9 (terminated)", readOnly: true };
  const title = (d: Doc) => inUse(d, k) && ((d.value(name) as string) || (d.value(roName) as string)) || `Character ${k + 1}`;
  return {
    key: area,
    title,
    present: d => inUse(d, k) && d.has(name),
    empty: d => !inUse(d, k)
      ? `Seat ${k + 1} is free. "Copy from…" puts another seat's character here.`
      : d.has(name) ? null
      : `${d.value(roName) || "This roster place"} has no character file (P${k}): the `
        + "character was never played. Make the character in the game to edit it here.",
    menus: [{ label: "Copy from…", choices: d => SEATS.filter(j => j !== k).map((j): Choice => ({
      label: `Seat ${j + 1}: ${character(j).title(d)}`,
      disabled: !inUse(d, j) ? "free" : !d.area(`p${j}`).has(0) ? "no character file" : null,
      run: w => {
        copyBytes(w, d, ["ro", SEAT * j], ["ro", SEAT * k], SEAT);
        copyBytes(w, d, [`p${j}`, 0], [area, 0], P_LEN);
      } })) }],
    actions: [{ label: "Delete", title: "Frees the seat as the game's terminate does: the name and the character file stay "
        + "until a character is made here, and the game does not show them",
      disabled: d => inUse(d, k) ? null : "the seat is free",
      run: w => w.set(used, false) }],
    sections: [
      { kind: "form", title: "Character", fields: [
        name,
        { ...roName, readOnly: true, note: "follows the name" },
        used,
        f("sex", "Sex", 0x4a, { t: "enum", values: [[0, "Male"], [1, "Female"]] }, { conf: "verified", src: ZTATS }),
        f("race", "Race", 0x69, RACES, { conf: "verified", src: ZTATS }),
        f("class", "Class", 0x6b, CLASSES, { conf: "verified", src: ZTATS }),
      ] },
      { kind: "form", title: "Attributes", fields: [
        f("hp", "Hit points", 0x59, u16, { max: 9999, conf: "verified", src: ZTATS }),
        f("str", "Strength", 0x5b, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("agi", "Agility", 0x5d, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("sta", "Stamina", 0x5f, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("cha", "Charisma", 0x61, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("wis", "Wisdom", 0x63, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("int", "Intelligence", 0x65, u16, { max: 99, conf: "verified", src: ZTATS }),
        f("exp", "Experience", 0x7a, u16, { max: 9999, conf: "verified", src: `${ZTATS}; the level is experience / 1000 + 1` }),
      ] },
      { kind: "form", title: "Supplies", fields: [
        f("food", "Food", 0x78, u16, { max: 9999, conf: "verified", src: ZTATS }),
        f("coins", "Coins (copper pence)", 0x67, u16, { max: 9999, conf: "verified",
          src: `${ZTATS}: 1234 shows as 12 gold crowns, 3 silver pieces, 4 copper pence` }),
        f("ships", "Enemy vessels destroyed", 0x49, u8, { conf: "verified", src: "u1talk.py ($822B)",
          note: "20 make the time machine appear" }),
      ] },
      { kind: "form", title: "Ready", fields: [
        f("weapon", "Weapon", 0x0d, READY_WEAPON, { conf: "verified", src: "MI $8810 (Ready), TW $9133 (sold: cleared)" }),
        f("armour", "Armour", 0x0e, READY_ARMOUR, { conf: "verified", src: "MI $881F (Ready), TW $914E (sold: cleared)" }),
        f("spell", "Spell", 0x0c, READY_SPELL, { conf: "verified", src: "MI $8801 (Ready)" }),
      ] },
      { kind: "grid", title: "Weapons", fields: counts(area, 0x17, WEAPONS, u8, { conf: "verified", src: ZTATS, max: 99 }, `${area}.weapon`) },
      { kind: "grid", title: "Armour", fields: counts(area, 0x11, ARMOUR, u8, { conf: "verified", src: ZTATS, max: 99 }, `${area}.armour`) },
      { kind: "grid", title: "Spells", fields: counts(area, 0x27, SPELLS, u8, { conf: "verified", src: ZTATS, max: 99 }, `${area}.spell`) },
      { kind: "grid", title: "Gems", fields: counts(area, 0x08, GEMS, u8, { conf: "verified", src: ZTATS, max: 99 }, `${area}.gem`) },
      { kind: "grid", title: "Vehicles", note: "not on Ztats; OU counts them at $8213 + the vehicle (horse 1)",
        fields: counts(area, 0x32, VEHICLES, u8, { conf: "verified", src: "OU ($8213,X: INC/DEC)", max: 99 }, `${area}.vehicle`) },
      { kind: "grid", title: "Quests done (the king's byte, bit 7)",
        fields: KINGS.map((n, q) => f(`quest${q}`, n, 0x3c + q, { t: "flag", mask: 0x80 },
          { conf: "verified", src: "u1talk.py (CA $8CB7, $821E + k)" })) },
      { kind: "form", title: "Where", fields: [
        f("continent", "Continent (0-3)", 0x02, u8, { max: 3, conf: "verified", src: "U1 notes (OU $9840)" }),
        f("x", "X", 0x06, u8, { max: 63, conf: "verified", src: "OU reads $81E8/$81E9 as it starts" }),
        f("y", "Y", 0x07, u8, { max: 63, conf: "verified", src: "OU reads $81E8/$81E9 as it starts" }),
        f("vehicle", "Riding", 0x0f, RIDING, { conf: "verified", src: "OU and SP ($81F1); the names MI $7930" }),
      ] },
    ],
  };
}

export function view(save: Ucsv): GameView {
  // RO and P0-P3 may be missing (a disk on which no character was made): a copy adds them
  const doc = new Doc([
    optionalSlotArea(save, "ro", "RO: the roster (at $B000)", 0, 4 * SEAT, 0xb000),
    ...SEATS.map(k => optionalSlotArea(save, `p${k}`, `P${k}: character ${k + 1} (at $81E2)`, k + 1, P_LEN, 0x81e2)),
  ]);
  return {
    game: 1, title: "Ultima I", doc,
    tabs: [{ title: "Characters", sections: [{ kind: "records", title: "Characters",
      records: SEATS.map(character) }] }],
    readOnly: null,
    remarks: [],
    warnings: () => [],
  };
}
