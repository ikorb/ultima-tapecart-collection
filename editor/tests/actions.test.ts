// The buttons, the warnings' fixes and the undo steps: what each writes,
// that it is one step, and that undo puts every byte back.

import { test } from "node:test";
import assert from "node:assert/strict";
import { decode, encode } from "../src/container/ucsv.ts";
import { viewOf } from "../src/games/index.ts";
import {
  allFields, bulkValues, withinRule,
  type Action, type GameView, type Section, type Field, type RecordDef,
} from "../src/games/model.ts";
import { OBJECTS } from "../src/games/u6names.ts";
import { NO_FIXTURES, fixture } from "./fixtures.ts";

const load = (g: number) => { const raw = fixture(`u${g}.seq`); const save = decode(raw); return { raw, save, v: viewOf(save) }; };

function field(v: GameView, id: string): Field {
  const f = allFields(v).find(x => x.field.id === id);
  assert.ok(f, id);
  return f.field;
}

function tabAction(v: GameView, tab: string, label: string): Action {
  const a = v.tabs.find(t => t.title === tab)?.actions?.find(x => x.label === label);
  assert.ok(a, `${tab}: ${label}`);
  return a;
}

function sectionsOf(v: GameView): Section[] {
  const out: Section[] = [];
  const walk = (secs: Section[]) => { for (const s of secs) { out.push(s); if (s.kind === "records") s.records.forEach(r => walk(r.sections)); } };
  v.tabs.forEach(t => walk(t.sections));
  return out;
}

function act(v: GameView, a: Action): void {
  assert.equal(a.disabled?.(v.doc) ?? null, null, `${a.label} is enabled`);
  v.doc.edit(w => a.run!(w, v.doc), a.label);
}

/** U6's inventory record of a party place. */
function inv(v: GameView, p: number): RecordDef {
  const s = v.tabs.find(t => t.title === "Inventory")!.sections[0];
  assert.ok(s.kind === "records");
  return s.records[p];
}
function row(v: GameView, p: number, k: number) {
  const t = inv(v, p).sections[k < 24 ? 1 : 0];
  assert.ok(t.kind === "table");
  return t.rows[k < 24 ? k : k - 24];
}
function choose(v: GameView, p: number, k: number, label: RegExp): void {
  const c = row(v, p, k).menu!(v.doc).find(x => label.test(x.label));
  assert.ok(c, `${label} for place ${p}, slot ${k}: ${row(v, p, k).menu!(v.doc).map(x => x.label).join(" | ")}`);
  assert.equal(c.disabled ?? null, null, c.label);
  v.doc.edit(c.run, c.label);
}

test("an undo step carries its label; a failed edit leaves nothing behind", { skip: NO_FIXTURES }, () => {
  const { v } = load(6);
  assert.equal(v.doc.undoLabel(), null);
  v.doc.set(field(v, "c0.str"), 25, "Strength: 9 → 25");
  assert.equal(v.doc.undoLabel(), "Strength: 9 → 25");
  v.doc.undo();
  assert.equal(v.doc.redoLabel(), "Strength: 9 → 25");
  v.doc.redo();
  const a = v.doc.area("save"), before = a.get(0x578c - 0x5400 + 1);
  assert.throws(() => v.doc.edit(w => { w.set(field(v, "c1.str"), 7); w.set(field(v, "c1.level"), 99); }));
  assert.equal(a.get(0x578c - 0x5400 + 1), before, "the first write of the failed step is undone");
  assert.equal(v.doc.undoLabel(), "Strength: 9 → 25");
});

test("putting a field back touches only its bytes, or a flag's bit", { skip: NO_FIXTURES }, () => {
  const { v, raw, save } = load(6);
  v.doc.set(field(v, "c0.poisoned"), true);
  v.doc.set(field(v, "c0.asleep"), true);
  v.doc.set(field(v, "karma"), 42);
  v.doc.revert(field(v, "c0.poisoned"));
  assert.equal(v.doc.value(field(v, "c0.poisoned")), false);
  assert.equal(v.doc.value(field(v, "c0.asleep")), true);
  v.doc.revert(field(v, "c0.asleep"));
  v.doc.revert(field(v, "karma"));
  assert.deepEqual(encode(save), raw);
  assert.equal(v.doc.undoLabel(), "Karma as opened");
});

test("the nearest value the game allows", { skip: NO_FIXTURES }, () => {
  const { v } = load(6);
  const mx = field(v, "c0.maxhp");
  assert.equal(withinRule(mx, 250), 240);
  assert.equal(withinRule(mx, 10), 30);
  assert.equal(withinRule(mx, 100), 90);
  assert.equal(withinRule(field(v, "c0.level"), 12), 8);
  assert.equal(withinRule(field(v, "c0.level"), 0), 1);
  assert.equal(withinRule(field(load(4).v, "p0.str"), 99), 50);
});

test("a grid of like fields gets all and none, others not", { skip: NO_FIXTURES }, () => {
  const byTitle = (v: GameView, t: string) => sectionsOf(v).find(s => s.title === t)!;
  const v6 = load(6).v;
  assert.deepEqual(bulkValues(byTitle(v6, "First circle")), { all: true, none: false, allLabel: "All", noneLabel: "None" });
  assert.equal(bulkValues(byTitle(v6, "Condition")), null, "it has its own button");
  assert.equal(bulkValues(byTitle(v6, "Flags")), null, "a person's flags: off on purpose");
  const v4 = load(4).v;
  assert.deepEqual(bulkValues(byTitle(v4, "Reagents")), { all: 99, none: 0, allLabel: "All 99", noneLabel: "All 0" });
  assert.equal(bulkValues(byTitle(load(5).v, "Quest items")), null, "bytes whose held value is not known");
});

test("U6: heal and cure everyone, one step", { skip: NO_FIXTURES }, () => {
  const { v, raw, save } = load(6);
  v.doc.set(field(v, "c0.poisoned"), true);
  v.doc.set(field(v, "c1.asleep"), true);
  v.doc.set(field(v, "c0.hp"), 3);
  const heal = tabAction(v, "Party", "Heal and cure everyone");
  act(v, heal);
  assert.equal(v.doc.value(field(v, "c0.hp")), v.doc.value(field(v, "c0.maxhp")));
  assert.equal(v.doc.value(field(v, "c0.poisoned")), false);
  assert.equal(v.doc.value(field(v, "c1.asleep")), false);
  assert.equal(heal.disabled!(v.doc), "everyone is well");
  v.doc.undo();
  assert.equal(v.doc.value(field(v, "c0.poisoned")), true);
  for (let k = 0; k < 3; k++) v.doc.undo();
  assert.deepEqual(encode(save), raw);
});

test("U6: every spell learnt, then none", { skip: NO_FIXTURES }, () => {
  const { v } = load(6);
  const spells = allFields(v).filter(f => f.field.id.startsWith("spell."));
  act(v, tabAction(v, "Spells", "Learn every spell"));
  assert.ok(spells.every(f => v.doc.value(f.field) === true));
  act(v, tabAction(v, "Spells", "Forget every spell"));
  assert.ok(spells.every(f => v.doc.value(f.field) === false));
  v.doc.undo();
  assert.ok(spells.every(f => v.doc.value(f.field) === true));
});

test("U6: things given, taken off, readied and stacked", { skip: NO_FIXTURES }, () => {
  const { v, raw, save } = load(6);
  const obj = (p: number, k: number) => v.doc.value(field(v, `inv${p}.${k}.obj`));
  const num = (p: number, k: number, what: string) => v.doc.value(field(v, `inv${p}.${k}.${what}`));
  const orb = OBJECTS.indexOf("Orb of the Moons"), sword = OBJECTS.indexOf("sword");
  assert.equal(obj(0, 0), orb);
  assert.equal(obj(0, 27), sword);
  assert.ok(row(v, 0, 5).empty!(v.doc), "an empty slot is empty");
  assert.ok(!row(v, 0, 0).empty!(v.doc));
  const free1 = [...Array(24).keys()].find(k => obj(1, k) === 0)!;
  choose(v, 0, 0, /^Give to /);
  assert.equal(obj(0, 0), 0);
  assert.equal(obj(1, free1), orb);
  choose(v, 0, 27, /^Take it off/);
  assert.equal(obj(0, 27), 0);
  const k = [...Array(24).keys()].find(j => obj(0, j) === sword)!;
  assert.equal(Number(num(0, k, "status")) & 8, 0, "not readied in the pack");
  choose(v, 0, k, /^Ready it \(weapon hand\)/);
  assert.equal(obj(0, 27), sword);
  assert.equal(num(0, 27, "status"), 0x18);
  // gold onto gold: Dupre's 30 coins (slot 2) take the Avatar's 5
  const gold = OBJECTS.indexOf("gold coin");
  assert.equal(obj(1, 1), gold);
  assert.equal(num(1, 1, "qty"), 30);
  v.doc.set(field(v, "inv0.10.obj"), gold); v.doc.set(field(v, "inv0.10.qty"), 5);
  choose(v, 0, 10, /^Give to Dupre/);
  assert.equal(num(1, 1, "qty"), 35);
  assert.equal(obj(0, 10), 0);
  while (v.doc.canUndo()) v.doc.undo();
  assert.deepEqual(encode(save), raw);
});

test("U6: Add an object goes to the first empty pack slot", { skip: NO_FIXTURES }, () => {
  const { v } = load(6);
  const pack = inv(v, 0).sections[1];
  const add = pack.actions!.find(a => a.label === "Add an object")!;
  const first = [...Array(24).keys()].find(k => v.doc.value(field(v, `inv0.${k}.obj`)) === 0)!;
  assert.equal(add.focus!(v.doc), `inv0.${first}.obj`);
  for (let k = 0; k < 24; k++) if (!v.doc.value(field(v, `inv0.${k}.obj`))) v.doc.set(field(v, `inv0.${k}.obj`), 0x60);
  assert.equal(add.focus!(v.doc), null);
  assert.equal(add.disabled!(v.doc), "the pack is full");
  assert.match(inv(v, 0).badge!(v.doc)!.title!, /^24 in the pack, 1 worn$/);
});

test("U6: each warning shows where, and its fix puts it right", { skip: NO_FIXTURES }, () => {
  const { v } = load(6);
  const fix = (re: RegExp) => {
    const w = v.warnings().find(x => re.test(x.text));
    assert.ok(w, `${re}: ${v.warnings().map(x => x.text).join(" | ")}`);
    assert.ok(w.id && allFields(v).some(f => f.field.id === w.id), `${w.text}: ${w.id}`);
    assert.ok(w.fix, w.text);
    v.doc.edit(w.fix.run, w.fix.label);
    return w;
  };
  v.doc.set(field(v, "c0.hp"), 200);
  assert.equal(fix(/more hit points/).id, "c0.hp");
  assert.equal(v.doc.value(field(v, "c0.hp")), v.doc.value(field(v, "c0.maxhp")));
  v.doc.set(field(v, "inv0.0.qty"), 3);                        // three Orbs in one slot
  fix(/does not stack/);
  assert.equal(v.doc.value(field(v, "inv0.0.qty")), 1);
  v.doc.set(field(v, "inv0.25.obj"), OBJECTS.indexOf("sword"));     // a second sword, on the head
  assert.match(fix(/on the head/).fix!.label, /pack/, "the weapon hand is taken: into the pack");
  assert.equal(v.doc.value(field(v, "inv0.25.obj")), 0);
  v.doc.set(field(v, "inv0.27.obj"), 0);
  v.doc.set(field(v, "inv0.25.obj"), OBJECTS.indexOf("sword"));
  assert.match(fix(/on the head/).fix!.label, /weapon hand/);
  assert.equal(v.doc.value(field(v, "inv0.27.obj")), OBJECTS.indexOf("sword"));
  assert.deepEqual(v.warnings(), []);
});

test("U3-U5: heal and cure, fill up", { skip: NO_FIXTURES }, () => {
  const v4 = load(4).v;
  v4.doc.set(field(v4, "p0.hp"), 12);
  v4.doc.set(field(v4, "p0.status"), 0xd0);
  act(v4, tabAction(v4, "Party", "Heal and cure the party"));
  assert.equal(v4.doc.value(field(v4, "p0.hp")), v4.doc.value(field(v4, "p0.maxhp")));
  assert.equal(v4.doc.value(field(v4, "p0.status")), 0xc7);
  const sup4 = sectionsOf(v4).find(s => s.title === "Supplies")!;
  act(v4, sup4.actions![0]);
  assert.deepEqual(["food", "gold", "torches", "gems", "keys"].map(id => v4.doc.value(field(v4, id))), [9999, 9999, 99, 99, 99]);
  v4.doc.set(field(v4, "p0.status"), 0xc4);                    // the dead stay dead
  v4.doc.set(field(v4, "p0.hp"), 0);
  assert.ok(tabAction(v4, "Party", "Heal and cure the party").disabled!(v4.doc));

  const v5 = load(5).v;
  v5.doc.set(field(v5, "c1.hp"), 1);
  act(v5, tabAction(v5, "Party", "Heal and cure everyone"));
  assert.equal(v5.doc.value(field(v5, "c1.hp")), v5.doc.value(field(v5, "c1.maxhp")));
  act(v5, sectionsOf(v5).find(s => s.title === "Supplies")!.actions![0]);
  assert.deepEqual(["food", "gold", "keys", "gems", "torches"].map(id => v5.doc.value(field(v5, id))), [9999, 9999, 99, 99, 99]);

  const v3 = load(3).v;
  v3.doc.set(field(v3, "plrs0.hp"), 1);
  v3.doc.set(field(v3, "plrs0.status"), 0xd0);
  act(v3, tabAction(v3, "Party", "Heal and cure the party"));
  assert.equal(v3.doc.value(field(v3, "plrs0.hp")), v3.doc.value(field(v3, "plrs0.maxhp")));
  assert.equal(v3.doc.value(field(v3, "plrs0.status")), 0xc7);
});
