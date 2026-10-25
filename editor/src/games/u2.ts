// Ultima II: the player record (Player disk track 35 sector 16, at $8E00)
// and the MOB/MON files of Earth's maps (256 bytes each), which are only
// shown as bytes.  On the cart the record and the files are units of U2's
// save log; the file holds each one's newest version.
//
// Sources: C64UltimaEditor (zoggins: the record's stats and items, all BCD),
// the U2 analysis (docs/reversing-notes/u2.md: +$13/+$14 the map,
// +$37 the planet, +$FF must be 0), the collection's build (ultima/games/u2/
// build.py: food, torches), dialogue/u2talk.py (+$36) and the launcher page.

import type { Ucsv } from "../container/ucsv.ts";
import {
  Doc, slotArea, bcd1, bcd2, u8, enumOf, counts,
  type Field, type GameView, type Enc, type Warning,
} from "./model.ts";

// the offsets first came from C64UltimaEditor (zoggins); each is now checked against the game
// seen on the game's Ztats screen with a distinct value in each field (tools/vice/editor_game_check.py)
const ZTATS = "U2's Ztats screen";
const ANALYSIS = "U2 analysis";

export const WEAPONS = ["Dagger", "Mace", "Axe", "Bow", "Sword", "Great sword", "Light sword", "Phaser", "Quick sword"];
export const ARMOUR = ["Cloth", "Leather", "Chain", "Plate", "Reflect", "Power"];
export const SPELLS = ["Light", "Ladder down", "Ladder up", "Passwall", "Surface", "Prayer", "Magic missile",
  "Blink", "Kill"];
export const ITEMS = ["Rings", "Wands", "Staffs", "Boots", "Cloaks", "Helms", "Gems", "Ankhs", "Red gems",
  "Skull keys", "Green gems", "Brass buttons", "Blue tassles", "Strange coins", "Green idols", "Try-lithiums"];
const ERAS = ["Time of Legends", "9,000,000 B.C. (Pangea)", "300 B.C.", "1990 A.D.", "2112 A.D. (Aftermath)"];
const MOB = ["00", "10", "20", "30", "40"], MON = ["00", "03", "10", "20", "30", "40"];

function r(id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field {
  return { id, label, area: "record", at, enc, conf: "verified", src: ZTATS, ...extra };
}

export function view(save: Ucsv): GameView {
  const doc = new Doc([
    slotArea(save, "record", "The player record (track 35 sector 16, at $8E00)", [11], 0x8e00),
    ...MOB.map((n, k) => slotArea(save, `mob${n}`, `MOB ${n} (at $3000)`, [k], 0x3000)),
    ...MON.map((n, k) => slotArea(save, `mon${n}`, `MON ${n}: the people of map ${n} (at $8F00)`, [5 + k], 0x8f00)),
  ]);
  const name = r("name", "Name", 0x00, { t: "text", n: 11, cs: "high", upper: true },
    { conf: "verified", src: "launcher page (a first byte of 0: no player)" });
  return {
    game: 2, title: "Ultima II", doc,
    tabs: [
      { title: "Player", sections: [
        { kind: "form", title: "Character", fields: [
          name,
          r("sex", "Sex", 0x10, { t: "enum", values: [[0xcd, "Male"], [0xc6, "Female"]] }),   // "M", "F"
          r("race", "Race", 0x12, enumOf(["Human", "Elf", "Dwarf", "Hobbit"])),
          r("class", "Class", 0x11, enumOf(["Fighter", "Cleric", "Wizard", "Thief"])),
        ] },
        { kind: "form", title: "Attributes", fields: [
          r("hp", "Hit points", 0x1b, bcd2, { conf: "verified", src: "launcher page" }),
          r("str", "Strength", 0x15, bcd1), r("agi", "Agility", 0x16, bcd1), r("sta", "Stamina", 0x17, bcd1),
          r("cha", "Charisma", 0x18, bcd1), r("wis", "Wisdom", 0x19, bcd1), r("int", "Intelligence", 0x1a, bcd1),
          r("exp", "Experience", 0x20, bcd2, { note: "the level is experience / 100" }),
        ] },
        { kind: "form", title: "Supplies", fields: [
          r("food", "Food", 0x1d, bcd2, { note: "whole rations; the hundredths are the byte after (ULTIMA reads $8E1F)" }),
          r("coins", "Coins", 0x22, bcd2),
          r("torches", "Torches", 0x2e, bcd1, { conf: "verified", src: "ultima/games/u2/build.py (the torch patch)" }),
          r("keys", "Keys", 0x2f, bcd1), r("tools", "Tools", 0x30, bcd1),
          r("blessing", "Father Antos's blessing", 0x36, { t: "nonzero", on: 1 }, { conf: "verified", src: "dialogue/u2talk.py" }),
        ] },
        { kind: "form", title: "Ready", fields: [
          r("weapon", "Weapon", 0x2b, enumOf(["Hands", ...WEAPONS]), { src: "ULTIMA $56E5 (Ztats: string $8E2B + $13)" }),
          r("armour", "Armour", 0x2c, enumOf(["Skin", ...ARMOUR]), { src: "ULTIMA $571A (Ztats: string $8E2C + $1D)" }),
          r("spell", "Spell", 0x2d, enumOf(["None", ...SPELLS]), { src: "ULTIMA $574B (Ztats: string $8E2D + $24)" }),
        ] },
      ] },
      { title: "Inventory", sections: [
        { kind: "grid", title: "Weapons", fields: counts("record", 0x41, WEAPONS, bcd1, { conf: "verified", src: ZTATS }, "weapon") },
        { kind: "grid", title: "Armour", fields: counts("record", 0x61, ARMOUR, bcd1, { conf: "verified", src: ZTATS }, "armour") },
        { kind: "grid", title: "Spells", fields: counts("record", 0x81, SPELLS, bcd1, { conf: "verified", src: ZTATS }, "spell") },
        { kind: "grid", title: "Items", fields: counts("record", 0xa0, ITEMS, bcd1, { conf: "verified", src: ZTATS }, "item") },
      ] },
      { title: "World", sections: [
        { kind: "form", title: "Where the player is",
          note: "Moving the player: x and y on the current map (0-63); the editor does not check what is there.",
          fields: [
            r("era", "Era or planet (MAP x_)", 0x13, u8, { readOnly: true, conf: "reference", src: ANALYSIS,
              note: ERAS.map((e, k) => `${k} ${e}`).join(", ") }),
            r("place", "Place (0 the surface)", 0x14, u8, { readOnly: true, conf: "reference", src: ANALYSIS }),
            r("planet", "Planet (0 = Earth)", 0x37, u8, { readOnly: true, conf: "reference", src: ANALYSIS }),
            r("x", "X", 0x24, u8, { max: 63, src: "ULTIMA reads $8E24/$8E25 as it starts and keeps them as the player moves" }),
            r("y", "Y", 0x25, u8, { max: 63, src: "ULTIMA reads $8E24/$8E25 as it starts and keeps them as the player moves" }),
          ] },
      ] },
    ],
    readOnly: null,
    remarks: [],
    warnings() {
      const out: Warning[] = [];
      if (!doc.value(name)) out.push({ text: "The player has no name: the game would offer to make a new one.", id: name.id });
      if (doc.area("record").get(0xff) !== 0) out.push({ text: "The record's last byte is not 0: the game would not take it as a player disk.",
        fix: { label: "Set it to 0", run: w => w.setByte("record", 0xff, 0) } });
      return out;
    },
  };
}
