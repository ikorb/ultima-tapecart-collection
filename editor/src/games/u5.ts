// Ultima V: ROSTER ($1000, 1024 bytes), PRTY.DATA ($BC00, 48), and the
// object lists LIST, SLIST, TLIST (2A) and TLIST (2B), which are only shown
// as bytes.
//
// Sources: Ultima V Remastered's editor (Drunella; src/common/editor.c,
// roster_t at $1000), the 2004 document it carries (Marc Winterrowd,
// "Ultima 5 File Formats (C64 version)", doc/u5_c64.txt, whose offsets
// include the load address), the U6 transfer's research (docs/developer/u6.md:
// ROSTER +$80 records) and the launcher page.  The readied-equipment code
// is 1 + the item's place in the armour/weapon/ring/amulet lists, 0 empty:
// slots set to 3 and 46 showed as Iron Helm and Am/Turning on the Avatar's
// Arms page.

import type { Ucsv } from "../container/ucsv.ts";
import {
  Doc, slotArea, bcd1, bcd2, u8, counts,
  type Field, type GameView, type Section, type RecordDef, type Enc, type Warning, type Action,
} from "./model.ts";

const KIT = "U5 Remastered editor";
const DOC = "2004 document (u5_c64.txt)";
const XFER = "U6 transfer research";
// seen on the game's Ztats pages (east/west) with a distinct value in each field (tools/vice/editor_game_check.py)
const ZTATS = "U5's Ztats";
const ATTR = { max: 30, text: "the game raises an attribute to 30 at most" };

export const ARMOUR = ["Leather helm", "Chain coif", "Iron helm", "Spiked helm", "Small shield",
  "Large shield", "Spiked shield", "Magic shield", "Jewel shield", "Cloth", "Leather", "Ring mail",
  "Scale mail", "Chain mail", "Plate mail", "Mystic armour"];
export const WEAPONS = ["Dagger", "Sling", "Club", "Flaming oil", "Main gauche", "Spear", "Throwing axe",
  "Short sword", "Mace", "Morning star", "Bow", "Arrows", "Crossbow", "Quarrels", "Long sword",
  "Two-handed hammer", "Two-handed axe", "Two-handed sword", "Halberd", "Chaos sword", "Magic bow",
  "Silver sword", "Magic axe", "Glass sword", "Jeweled sword", "Mystic sword"];
export const RINGS = ["Ring of invisibility", "Ring of protection", "Ring of regeneration"];
export const AMULETS = ["Amulet of turning", "Spiked collar", "Ankh"];
export const SPELLS = ["In Lor", "Grav Por", "An Zu", "An Nox", "Mani", "An Ylem", "An Sanct", "An Xen Corp",
  "Rel Hur", "In Wis", "Kal Xen", "In Xen Mani", "Vas Lor", "Vas Flam", "In Flam Grav", "In Nox Grav",
  "In Zu Grav", "In Por", "An Grav", "In Sanct", "In Sanct Grav", "Uus Por", "Des Por", "Wis Quas",
  "In Bet Xen", "An Ex Por", "In Ex Por", "Vas Mani", "In Zu", "Rel Tym", "In Vas Por Ylem",
  "Quas An Wis", "In An", "Wis An Ylem", "An Xen Ex", "Rel Xen Bet", "Sanct Lor", "Xen Corp",
  "In Quas Xen", "In Quas Wis", "In Nox Hur", "In Quas Corp", "In Mani Corp", "Kal Xen Corp",
  "In Vas Grav Corp", "In Flam Hur", "Vas Rel Por", "An Tym"];
export const SCROLLS = ["Vas Lor", "Rel Hur", "In Sanct", "In An", "In Quas Wis", "Kal Xen Corp",
  "In Mani Corp", "An Tym"];
export const POTIONS = ["Blue", "Yellow", "Red", "Green", "Orange", "Purple", "Black", "White"];
export const REAGENTS = ["Sulfurous ash", "Ginseng", "Garlic", "Spider silk", "Blood moss", "Black pearl",
  "Nightshade", "Mandrake root"];
const VIRTUES = ["Honesty", "Compassion", "Valor", "Justice", "Sacrifice", "Honor", "Spirituality", "Humility"];
const TOWNS = ["none", "Moonglow", "Britain", "Jhelom", "Yew", "Minoc", "Trinsic", "Skara Brae", "New Magincia"];
const DUNGEONS = ["Deceit", "Despise", "Destard", "Wrong", "Covetous", "Shame", "Hythloth", "Doom"];

const SEX: Enc = { t: "enum", values: [[0x3e, "Male"], [0x3d, "Female"]] };
const CLASS: Enc = { t: "enum", values: [[0xc1, "Avatar"], [0xc2, "Bard"], [0xc6, "Fighter"], [0xcd, "Mage"]] };
const STATUS: Enc = { t: "enum", values: [[0xc7, "Good"], [0xd0, "Poisoned"], [0xd3, "Sleeping"], [0xc4, "Dead"]] };
const EQUIP: Enc = { t: "enum", values: [[0, "(nothing)"],
  ...[...ARMOUR, ...WEAPONS, ...RINGS, ...AMULETS].map((n, k) => [k + 1, n] as [number, string])] };
const GOOD = 0xc7, DEAD = 0xc4;
const SHADOWLORD: Enc = { t: "enum", values: [...TOWNS.map((t, k) => [k, t] as [number, string]), [0xff, "destroyed"]] };

function r(id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field {
  return { id, label, area: "roster", at, enc, conf: "reference", src: KIT, ...extra };
}

function character(i: number): RecordDef {
  const s = 0x80 + i * 16;
  const name = r(`c${i}.name`, "Name", i * 8, { t: "text", n: 8, cs: "u5" }, { conf: "verified", src: "launcher page" });
  return {
    key: `c${i}`,
    title: d => (d.value(name) as string) || `Roster place ${i + 1}`,
    present: d => !!d.value(name),
    sections: [
      { kind: "form", title: "Character", fields: [
        name,
        r(`c${i}.sex`, "Sex", s + 1, SEX, { conf: "verified", src: `${XFER}; ${ZTATS}` }),
        r(`c${i}.class`, "Class", s + 2, CLASS, { conf: "verified", src: `${XFER}; ${ZTATS}` }),
        r(`c${i}.status`, "Status", s + 3, STATUS, { conf: "verified", src: `launcher page; ${ZTATS}` }),
        r(`c${i}.where`, "In the party (0), else the inn's place", s + 0, u8, { src: DOC,
          note: "only the first six places can be in the party" }),
        r(`c${i}.level`, "Level", s + 0x0e, u8, { conf: "verified", src: XFER, rule: { min: 1, max: 8, text: "the game's levels are 1-8" } }),
      ] },
      { kind: "form", title: "Attributes", fields: [
        r(`c${i}.str`, "Strength", s + 4, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        r(`c${i}.dex`, "Dexterity", s + 5, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        r(`c${i}.int`, "Intelligence", s + 6, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}`, rule: ATTR }),
        r(`c${i}.mp`, "Magic points", s + 7, bcd1, { conf: "verified", src: `${XFER}; ${ZTATS}` }),
        r(`c${i}.hp`, "Hit points", s + 8, bcd2, { conf: "verified", src: "launcher page" }),
        r(`c${i}.maxhp`, "Maximum hit points", s + 0x0a, bcd2, { conf: "verified", src: XFER,
          rule: { min: 30, max: 240, step: 30, text: "the game keeps it at 30 x the level (1-8)" } }),
        r(`c${i}.exp`, "Experience", s + 0x0c, bcd2, { conf: "verified", src: XFER }),
      ] },
      { kind: "form", title: "Readied", note: "the game puts each readied item in the next free slot",
        fields: [0, 1, 2, 3, 4, 5].map(k => r(`c${i}.eq${k}`, `Slot ${k + 1}`, 0x190 + i * 6 + k, EQUIP,
          { conf: "verified", src: `${ZTATS} (Arms)` })) },
    ],
  };
}

export function view(save: Ucsv): GameView {
  const doc = new Doc([
    slotArea(save, "roster", "ROSTER (Britannia disk, at $1000)", [0], 0x1000),
    slotArea(save, "party", "PRTY.DATA (at $BC00)", [1], 0xbc00),
    slotArea(save, "list", "LIST (at $4A00)", [2], 0x4a00),
    slotArea(save, "slist", "SLIST (at $4A00)", [3], 0x4a00),
    slotArea(save, "tlist", "TLIST on Britannia (at $4A00)", [4], 0x4a00),
    slotArea(save, "tlist2", "TLIST on the Underworld disk (at $4A00)", [5], 0x4a00),
  ]);
  const p = (id: string, label: string, at: number, enc: Enc, extra: Partial<Field> = {}): Field =>
    ({ id, label, area: "party", at, enc, conf: "reference", src: DOC, ...extra });
  const records = Array.from({ length: 16 }, (_, i) => character(i));
  const inventory: Section[] = [
    { kind: "form", title: "Supplies", actions: [] as Action[], fields: [
      r("food", "Food", 0x180, bcd2, { conf: "verified", src: ZTATS }), r("gold", "Gold", 0x182, bcd2, { conf: "verified", src: ZTATS }),
      r("keys", "Keys", 0x184, bcd1, { conf: "verified", src: ZTATS }), r("gems", "Gems", 0x185, bcd1, { conf: "verified", src: ZTATS }),
      r("torches", "Torches", 0x186, bcd1, { conf: "verified", src: ZTATS }),
      r("grapple", "Grapples", 0x187, bcd1, { conf: "verified", src: `${ZTATS} (listed when held, without a count)` }),
      r("carpets", "Magic carpets", 0x188, bcd1),
      r("skullkeys", "Skull keys", 0x1f7, bcd1),
      r("spyglass", "Spyglasses", 0x1f3, bcd1), r("sextant", "Sextants", 0x1f5, bcd1),
      r("plans", "H.M.S. Cape plans", 0x1f4, bcd1),
      r("watch", "Pocket watch", 0x1f6, { t: "nonzero", on: 0xff }, { src: `${DOC}: $FF = held` }),
    ] },
    { kind: "grid", title: "Quest items", note: "0 = not held; the value the game writes for one held is not documented",
      fields: [["Shard of Falsehood", 0x1f0], ["Shard of Hatred", 0x1f1], ["Shard of Cowardice", 0x1f2],
        ["Amulet of Lord British", 0x1f8], ["Crown of Lord British", 0x1f9], ["Sceptre of Lord British", 0x1fa],
        ["Black badge", 0x1fb], ["Sandalwood box", 0x1fc]]
        .map(([n, at], k) => r(`quest.${k}`, n as string, at as number, u8, { src: DOC })) },
    { kind: "grid", title: "Weapons", fields: counts("roster", 0x210, WEAPONS, bcd1, { src: KIT }, "weapon") },
    { kind: "grid", title: "Armour", fields: counts("roster", 0x200, ARMOUR, bcd1, { conf: "verified", src: ZTATS }, "armour") },
    { kind: "grid", title: "Rings and amulets", fields: [
      ...counts("roster", 0x22a, RINGS, bcd1, { src: KIT }, "ring"),
      ...counts("roster", 0x22d, AMULETS, bcd1, { src: KIT }, "amulet")] },
    { kind: "grid", title: "Reagents", fields: counts("roster", 0x2a0, REAGENTS, bcd1, { conf: "verified", src: ZTATS }, "reagent") },
    { kind: "grid", title: "Spells", fields: counts("roster", 0x240, SPELLS, bcd1, { conf: "verified", src: ZTATS }, "spell") },
    { kind: "grid", title: "Scrolls", fields: counts("roster", 0x270, SCROLLS, bcd1, { conf: "verified", src: ZTATS }, "scroll") },
    { kind: "grid", title: "Potions", fields: counts("roster", 0x278, POTIONS, bcd1, { src: KIT }, "potion") },
  ];
  const fill = [0x180, 0x182, 0x184, 0x185, 0x186];
  const supplies = inventory[0];
  if (supplies.kind === "form") {
    const fs = supplies.fields.filter(f => fill.includes(f.at));
    const full = (f: Field) => f.enc.t === "bcd" ? 10 ** (2 * f.enc.n) - 1 : 0;
    supplies.actions = [{ label: "Fill up", title: fs.map(f => `${f.label} ${full(f)}`).join(", "),
      disabled: () => fs.every(f => doc.value(f) === full(f)) ? "all full" : null,
      run: w => fs.forEach(f => w.set(f, full(f))) }];
  }
  const named = (i: number) => !!doc.value(r("", "", i * 8, { t: "text", n: 8, cs: "u5" }));
  const ill = (i: number) => { const s = 0x80 + i * 16;
    return named(i) && doc.value(r("", "", s + 3, u8)) !== DEAD
      && (doc.value(r("", "", s + 8, bcd2)) !== doc.value(r("", "", s + 0x0a, bcd2)) || doc.value(r("", "", s + 3, u8)) !== GOOD); };
  const heal: Action = { label: "Heal and cure everyone", title: "Every character's hit points to the maximum, status Good; the dead stay dead",
    disabled: () => [...Array(16).keys()].some(ill) ? null : "everyone is well",
    run: w => { for (let i = 0; i < 16; i++) if (ill(i)) { const s = 0x80 + i * 16;
      w.set(r("", "", s + 8, bcd2), doc.value(r("", "", s + 0x0a, bcd2)) as number); w.set(r("", "", s + 3, u8), GOOD); } } };
  const quest: Section[] = [
    { kind: "form", title: "The Shadowlords", fields: [
      r("sl.f", "Falsehood", 0x189, SHADOWLORD, { src: DOC }),
      r("sl.h", "Hatred", 0x18a, SHADOWLORD, { src: DOC }),
      r("sl.c", "Cowardice", 0x18b, SHADOWLORD, { src: DOC }),
    ] },
    { kind: "grid", title: "Shrine quests ordained", fields: VIRTUES.map((v, k) => r(`ord.${k}`, v, 0x18c, { t: "flag", mask: 1 << k }, { src: DOC })) },
    { kind: "grid", title: "Shrine quests completed", fields: VIRTUES.map((v, k) => r(`done.${k}`, v, 0x18e, { t: "flag", mask: 1 << k }, { src: DOC })) },
    { kind: "grid", title: "Shrines destroyed", fields: VIRTUES.map((v, k) => r(`shrine.${k}`, v, 0x238 + k, { t: "flag", mask: 0x80 }, { src: DOC })) },
    { kind: "grid", title: "Dungeons open (unsealed)", fields: DUNGEONS.map((v, k) => r(`dng.${k}`, v, 0x230 + k, { t: "flag", mask: 0x80 }, { src: DOC })) },
    { kind: "grid", title: "Moonstones held", note: "a stone not held is buried at the x, y below (World tab)",
      fields: VIRTUES.map((v, k) => r(`moon.${k}`, v, 0x290 + k, { t: "nonzero", on: 0xff }, { src: DOC })) },
  ];
  const world: Section[] = [
    { kind: "form", title: "Time and the party", fields: [
      p("karma", "Karma", 0x28, bcd1, { conf: "verified", src: "U5 Remastered editor (reads $BC28)" }),
      p("year", "Year", 0x18, bcd2), p("month", "Month", 0x1a, bcd1, { min: 1, max: 13 }),
      p("day", "Day", 0x1b, bcd1, { min: 1, max: 28 }), p("hour", "Hour", 0x1c, bcd1, { max: 23 }),
      p("minute", "Minute", 0x1d, bcd1, { max: 59 }),
      p("torch", "Torch turns left", 0x0e, u8), p("light", "Light spell turns left", 0x0f, u8),
      p("x", "X", 0x2b, u8, { readOnly: true, note: "two copies, one relative to the loaded map: not editable" }),
      p("y", "Y", 0x2c, u8, { readOnly: true }),
    ] },
    { kind: "grid", title: "Buried moonstones: x", fields: counts("roster", 0x280, VIRTUES, u8, { src: DOC }, "moonx") },
    { kind: "grid", title: "Buried moonstones: y", fields: counts("roster", 0x288, VIRTUES, u8, { src: DOC }, "moony") },
    { kind: "grid", title: "Buried moonstones: in the Underworld ($FF) or Britannia (0)",
      fields: counts("roster", 0x298, VIRTUES, u8, { src: DOC }, "moonz") },
  ];
  return {
    game: 5, title: "Ultima V", doc,
    tabs: [
      { title: "Party", sections: [{ kind: "records", title: "Roster", records }], actions: [heal] },
      { title: "Inventory", sections: inventory },
      { title: "Quest", sections: quest },
      { title: "World", sections: world },
    ],
    readOnly: null,
    remarks: [],
    warnings() {
      const out: Warning[] = [];
      for (let i = 0; i < 16; i++) {
        const s = 0x80 + i * 16;
        const name = doc.value(r("", "", i * 8, { t: "text", n: 8, cs: "u5" }));
        if (!name) continue;
        const hp = doc.value(r("", "", s + 8, bcd2)) as number, mx = doc.value(r("", "", s + 0x0a, bcd2)) as number;
        if (hp > mx) out.push({ text: `${name} has more hit points (${hp}) than the maximum (${mx}).`, id: `c${i}.hp`,
          fix: { label: `Set to ${mx}`, run: w => w.set(r("", "", s + 8, bcd2), mx) } });
        if (i >= 6 && doc.value(r("", "", s, u8)) === 0)
          out.push({ text: `${name} is marked as in the party, but only the first six places can be.`, id: `c${i}.where` });
      }
      if (!doc.value(r("", "", 0, { t: "text", n: 8, cs: "u5" })))
        out.push({ text: "The Avatar has no name: the game would say there is no saved game.", id: "c0.name" });
      return out;
    },
  };
}
