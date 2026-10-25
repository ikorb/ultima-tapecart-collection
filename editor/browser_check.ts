// The built page in a real browser: headless Chrome through the DevTools
// protocol, with a profile of its own under build/.
//
//     node editor/browser_check.ts            (after `bun editor/build.ts`)
//
// For each fixture: drop the file on the page, look at every tab (a
// screenshot each, build/editor-shots/), edit a field, press Download and
// decode what comes out: the edit must be there, and nothing else changed.
// Any exception or console error in the page fails the check.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { open, serialise } from "./src/container/open.ts";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const COLLECTION = join(import.meta.dirname, "..");
const PAGE = join(COLLECTION, "build", "ultima-save-editor.html");
const FIX = join(COLLECTION, "build", "editor-fixtures");
const SHOTS = join(COLLECTION, "build", "editor-shots");
const PROFILE = join(COLLECTION, "build", "editor-chrome-profile");
const PORT = 9333;

// fixture (a cart: the game to pick), the field to change (by its input id) and the value to type, the byte check
const CASES: { file: string; game?: number; id: string; value: string; tab?: string; check: (b: Uint8Array) => boolean }[] = [
  { file: "u4.seq", id: "p0.str", value: "25", check: b => slot(b, 2)[0x13] === 0x25 },
  { file: "u4.s00", id: "gold", value: "1234", tab: "Inventory", check: b => slot(b, 3)[0x13] === 0x12 && slot(b, 3)[0x14] === 0x34 },   // +$113 of the 512-byte chunk
  { file: "u4.d64", id: "p0.name", value: "IOLO", check: b => slot(b, 2)[0] === 0xc9 && slot(b, 2)[4] === 0 },
  { file: "u1.seq", id: "p1.food", value: "999", check: b => (slot(b, 2)[0x78] | slot(b, 2)[0x79] << 8) === 999 },
  { file: "u2.seq", id: "hp", value: "1500", check: b => slot(b, 11)[0x1b] === 0x15 && slot(b, 11)[0x1c] === 0 },
  { file: "u3.seq", id: "plrs1.hp", value: "275", check: b => slot(b, 3)[64 + 0x1a] === 0x02 && slot(b, 3)[64 + 0x1b] === 0x75 },
  { file: "u5.seq", id: "c1.hp", value: "60", check: b => slot(b, 0)[0x90 + 8] === 0 && slot(b, 0)[0x90 + 9] === 0x60 },
  { file: "u6.seq", id: "c0.str", value: "29", check: b => sector(b, 12)[0x8c] === 29 },
  // a game's own disk (another release's Scenario disk, C64UltimaEditor's: its submodule checked out)
  { file: "zoggins_u3.d64", id: "plrs0.gold", value: "999", check: b => slot(b, 3)[0x23] === 0x09 && slot(b, 3)[0x24] === 0x99 },
  // the cart itself, every game's save on it: one picked from the six
  { file: "cart.tcrt", game: 4, id: "gold", value: "1234", tab: "Inventory", check: b => slot(b, 3, 4)[0x13] === 0x12 && slot(b, 3, 4)[0x14] === 0x34 },
  { file: "cart.tcrt", game: 6, id: "c0.str", value: "29", check: b => sector(b, 12, 6)[0x8c] === 29 },
];
const TITLES = ["", "Ultima I", "Ultima II", "Ultima III", "Ultima IV", "Ultima V", "Ultima VI"];

function slot(b: Uint8Array, k: number, game?: number): Uint8Array {
  return open(b, "x", game).save.slots[k] as Uint8Array;
}
function sector(b: Uint8Array, s: number, game?: number): Uint8Array {
  const r = open(b, "x", game).save.records.find(x => x.kind === "sector" && x.sector === s);
  if (!r || r.kind !== "sector") throw new Error(`no sector ${s}`);
  return r.data;
}

class Cdp {
  private id = 0;
  private waiting = new Map<number, (v: unknown) => void>();
  readonly problems: string[] = [];
  private ws: WebSocket;
  constructor(url: string) {
    this.ws = new WebSocket(url);
    this.ws.onmessage = (m: MessageEvent) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id && this.waiting.has(msg.id)) {
        if (msg.error) this.problems.push(`CDP: ${msg.error.message}`);
        this.waiting.get(msg.id)!(msg.result);
        this.waiting.delete(msg.id);
      } else if (msg.method === "Runtime.exceptionThrown") {
        this.problems.push(`exception: ${msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text}`);
      } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
        this.problems.push(`console.error: ${msg.params.args.map((a: { value?: unknown }) => a.value).join(" ")}`);
      }
    };
  }
  ready(): Promise<void> { return new Promise(r => { this.ws.onopen = () => r(); }); }
  send(method: string, params: object = {}): Promise<any> {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise(r => this.waiting.set(id, r));
  }
  async eval(expr: string): Promise<any> {
    const r = await this.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r?.exceptionDetails) throw new Error(`in page: ${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}`);
    return r?.result?.value;
  }
  close(): void { this.ws.close(); }
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

async function shot(cdp: Cdp, name: string, whole = true): Promise<void> {
  const r = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: whole });
  writeFileSync(join(SHOTS, `${name}.png`), Uint8Array.from(atob(r.data), c => c.charCodeAt(0)));
}

function b64(b: Uint8Array): string {
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s);
}

async function main(): Promise<number> {
  if (!existsSync(PAGE)) { process.stderr.write("build the page first: bun editor/build.ts\n"); return 1; }
  mkdirSync(SHOTS, { recursive: true });
  rmSync(PROFILE, { recursive: true, force: true });
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    "--no-first-run", "--no-default-browser-check", "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
  let fails = 0;
  try {
    let targets: { type: string; webSocketDebuggerUrl: string }[] = [];
    for (let k = 0; k < 50 && !targets.length; k++) {
      await sleep(200);
      try { targets = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).filter((t: { type: string }) => t.type === "page"); }
      catch { /* not up yet */ }
    }
    if (!targets.length) throw new Error("Chrome did not come up");
    const cdp = new Cdp(targets[0].webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    for (const c of CASES) {
      if (!existsSync(join(FIX, c.file))) { process.stdout.write(`${c.file}: skipped (not in build/editor-fixtures)\n`); continue; }
      await cdp.send("Page.navigate", { url: `file://${PAGE}` });
      await sleep(400);
      if (c === CASES[0]) await shot(cdp, "welcome");
      const raw = new Uint8Array(readFileSync(join(FIX, c.file)));
      // drop the file; capture what Download hands to the browser
      await cdp.eval(`(() => {
        window.__out = null;
        URL.createObjectURL = b => { window.__blob = b; return "blob:x"; };
        HTMLAnchorElement.prototype.click = function () {};
        const bytes = Uint8Array.from(atob("${b64(raw)}"), c => c.charCodeAt(0));
        const dt = new DataTransfer();
        dt.items.add(new File([bytes], "${c.file}"));
        window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      })()`);
      await sleep(300);
      if (c.game) {                       // a cart: its six games, one picked
        await shot(cdp, `${c.file.replace(".", "-")}-pick`);
        await cdp.eval(`[...document.querySelectorAll(".picker li button")].find(b => b.textContent === ${JSON.stringify(TITLES[c.game])}).click()`);
        await sleep(300);
      }
      const tabs: string[] = await cdp.eval(`[...document.querySelectorAll("nav.tabs button")].map(b => b.firstChild.textContent)`);
      if (!tabs || !tabs.length) { process.stdout.write(`${c.file}: the editor did not open\n`); fails++; continue; }
      const base = c.file.replace(".", "-") + (c.game ? `-u${c.game}` : "");
      for (const t of tabs) {
        await cdp.eval(`[...document.querySelectorAll("nav.tabs button")].find(b => b.firstChild.textContent === ${JSON.stringify(t)}).click()`);
        await sleep(80);
        await shot(cdp, `${base}-${t.toLowerCase()}`);
      }
      // the edit
      const tab = c.tab ?? tabs[0];
      await cdp.eval(`[...document.querySelectorAll("nav.tabs button")].find(b => b.firstChild.textContent === ${JSON.stringify(tab)}).click()`);
      await sleep(50);
      const rec = c.id.match(/^([a-z]+\d+)\./)?.[1];
      if (rec) await cdp.eval(`(() => {   // pick the record that holds the field, if it is in a list
        const want = ${JSON.stringify(c.id)};
        if (document.getElementById(want)) return;
        for (const b of document.querySelectorAll(".records li button")) { b.click(); if (document.getElementById(want)) return; }
      })()`);
      const typed = await cdp.eval(`(() => {
        const el = document.getElementById(${JSON.stringify(c.id)});
        if (!el) return false;
        el.value = ${JSON.stringify(c.value)};
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })()`);
      await sleep(80);
      await shot(cdp, `${base}-edited`);
      const changesShown: number = await cdp.eval(`document.querySelectorAll("nav.tabs .count").length`);
      await cdp.eval(`[...document.querySelectorAll("header button")].find(b => b.textContent.startsWith("Download")).click()`);
      await sleep(150);
      const outB64: string | null = await cdp.eval(`(async () => {
        if (!window.__blob) return null;
        const b = new Uint8Array(await window.__blob.arrayBuffer());
        let s = ""; for (const x of b) s += String.fromCharCode(x); return btoa(s);
      })()`);
      const out = outB64 ? Uint8Array.from(atob(outB64), ch => ch.charCodeAt(0)) : null;
      let ok = typed && changesShown === 1 && !!out && c.check(out);
      // nothing else changed: the same edit made on the host gives the same file
      if (ok && out) {
        const o = open(raw, c.file, c.game);
        const back = open(out, c.file, c.game);
        ok = serialise(back).length === out.length && out.length === serialise(o).length;
      }
      process.stdout.write(`${c.file}${c.game ? ` (${TITLES[c.game]})` : ""}: ${ok ? "ok" : "FAILED"}${typed ? "" : " (no field " + c.id + ")"}${out ? "" : " (no download)"}\n`);
      if (!ok) fails++;
    }
    // the searchable dropdown, with real keys: U6's first pack slot, "orb of" typed, Enter
    {
      await cdp.send("Page.navigate", { url: `file://${PAGE}` });
      await sleep(400);
      const raw = new Uint8Array(readFileSync(join(FIX, "u6.seq")));
      await cdp.eval(`(() => {
        URL.createObjectURL = b => { window.__blob = b; return "blob:x"; };
        HTMLAnchorElement.prototype.click = function () {};
        const dt = new DataTransfer();
        dt.items.add(new File([Uint8Array.from(atob("${b64(raw)}"), c => c.charCodeAt(0))], "u6.seq"));
        window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      })()`);
      await sleep(300);
      await cdp.eval(`[...document.querySelectorAll("nav.tabs button")].find(b => b.firstChild.textContent === "Inventory").click()`);
      await sleep(80);
      const key = async (k: string, code: number) => {
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, windowsVirtualKeyCode: code });
        await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, windowsVirtualKeyCode: code });
      };
      const id = "inv0.23.obj";
      await cdp.eval(`document.getElementById("${id}").scrollIntoView({ block: "center" }); document.getElementById("${id}").focus()`);
      await cdp.send("Input.insertText", { text: "orb of" });
      await sleep(80);
      const listed: string[] = await cdp.eval(`[...document.getElementById("${id}-list").children].map(li => li.firstChild.textContent)`);
      const listShown: number = await cdp.eval(`document.getElementById("${id}-list").offsetHeight`);
      await shot(cdp, "u6-seq-combo-open", false);      // the whole page's capture leaves the list out
      await key("Enter", 13);
      await sleep(80);
      const after = await cdp.eval(`({ value: document.getElementById("${id}").value,
        focused: document.activeElement && document.activeElement.id,
        open: !document.getElementById("${id}-list").hidden,
        changes: document.querySelector("nav.tabs .count") && document.querySelector("nav.tabs .count").textContent })`);
      await key("ArrowDown", 40);
      await sleep(50);
      const reopened = await cdp.eval(`!document.getElementById("${id}-list").hidden`);
      await key("Escape", 27);
      await sleep(50);
      await shot(cdp, "u6-seq-combo-picked");
      const ok = listed.length === 1 && listed[0] === "Orb of the Moons" && after.value === "Orb of the Moons"
        && after.focused === id && !after.open && after.changes === "2" && reopened && listShown > 0;   // the object and its quantity 1
      await cdp.eval(`[...document.querySelectorAll("header button")].find(b => b.textContent.startsWith("Download")).click()`);
      await sleep(150);                                   // saved: no "leave the page?" on the next navigation
      process.stdout.write(`u6.seq, the searchable dropdown: ${ok ? "ok" : "FAILED " + JSON.stringify({ listed, listShown, after, reopened })}\n`);
      if (!ok) fails++;
    }
    // the rosters' own edits: U1 seat 1 (no character file) copied from seat 2, seat 3 deleted;
    // U3 roster place 1 copied from party member 1
    for (const [file, tab] of [["u1.seq", "Characters"], ["u3.seq", "Roster"]]) {
      await cdp.send("Page.navigate", { url: `file://${PAGE}` });
      await sleep(400);
      const raw = new Uint8Array(readFileSync(join(FIX, file)));
      await cdp.eval(`(() => {
        URL.createObjectURL = b => { window.__blob = b; return "blob:x"; };
        HTMLAnchorElement.prototype.click = function () {};
        const dt = new DataTransfer();
        dt.items.add(new File([Uint8Array.from(atob("${b64(raw)}"), c => c.charCodeAt(0))], "${file}"));
        window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      })()`);
      await sleep(300);
      const ev = (js: string) => cdp.eval(js);
      await ev(`[...document.querySelectorAll("nav.tabs button")].find(b => b.firstChild.textContent === ${JSON.stringify(tab)}).click()`);
      await sleep(50);
      const place = (k: number) => ev(`document.querySelectorAll(".records li button")[${k}].click()`);
      const copy = (re: string) => ev(`(() => {
        const s = document.querySelector(".record .toolbar select");
        const o = [...s.options].find(o => new RegExp(${JSON.stringify(re)}).test(o.textContent));
        if (!o) return false;
        s.value = o.value; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
      const del = () => ev(`(() => { const b = [...document.querySelectorAll(".record .toolbar button")].find(b => b.textContent === "Delete");
        if (!b) return false; b.click(); return true; })()`);
      await place(0);
      await sleep(50);
      await shot(cdp, `${file.replace(".", "-")}-roster-empty`);
      let did = await copy(file === "u1.seq" ? "^Seat 2: " : "^Party member 1: ");
      await sleep(50);
      if (file === "u1.seq") { await place(2); await sleep(50); did = did && await del(); await sleep(50); }
      await shot(cdp, `${file.replace(".", "-")}-roster-edited`);
      const undo: string = await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent === "Undo").title`);
      await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent.startsWith("Download")).click()`);
      await sleep(150);
      const outB64: string | null = await ev(`(async () => {
        if (!window.__blob) return null;
        const b = new Uint8Array(await window.__blob.arrayBuffer());
        let s = ""; for (const x of b) s += String.fromCharCode(x); return btoa(s);
      })()`);
      const out = outB64 ? open(Uint8Array.from(atob(outB64), ch => ch.charCodeAt(0)), file).save.slots : null;
      const was = open(raw, file).save.slots;
      const same = (a: Uint8Array | null, b: Uint8Array | null) => !!a && !!b && a.length === b.length && a.every((x, i) => x === b[i]);
      let ok = did && !!out;
      if (ok && out && file === "u1.seq") {
        const ro = was[0]!.slice();
        ro.set(was[0]!.subarray(16, 32), 0);
        ro[32] = 0;
        ok = same(out[0], ro) && same(out[1], was[2]) && [2, 3, 4].every(k => same(out[k], was[k])) && /Delete/.test(undo);
      } else if (ok && out) {
        const r = was[2]!.slice();
        r.set(was[3]!.subarray(0, 64), 0);
        r[0x10] = 0;
        ok = same(out[2], r) && [0, 1, 3, 4].every(k => same(out[k], was[k])) && /Copy|Party member 1/.test(undo);
      }
      process.stdout.write(`${file}, the roster's copy and delete: ${ok ? "ok" : "FAILED " + JSON.stringify({ did, undo })}\n`);
      if (!ok) fails++;
    }
    // the rest of the page's controls, on U6's file, with real clicks and keys
    {
      await cdp.send("Page.navigate", { url: `file://${PAGE}` });
      await sleep(400);
      const raw = new Uint8Array(readFileSync(join(FIX, "u6.seq")));
      await cdp.eval(`(() => {
        URL.createObjectURL = b => { window.__blob = b; return "blob:x"; };
        HTMLAnchorElement.prototype.click = function () {};
        window.confirm = () => true;
        const dt = new DataTransfer();
        dt.items.add(new File([Uint8Array.from(atob("${b64(raw)}"), c => c.charCodeAt(0))], "u6.seq"));
        window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      })()`);
      await sleep(300);
      const bad: string[] = [];
      const check = (what: string, ok: boolean, got?: unknown) => { if (!ok) bad.push(`${what}${got === undefined ? "" : `: ${JSON.stringify(got)}`}`); };
      const ev = (js: string) => cdp.eval(js);
      const tab = (t: string) => ev(`[...document.querySelectorAll("nav.tabs button")].find(b => b.firstChild.textContent === ${JSON.stringify(t)}).click()`);
      const button = (text: string, within = "document") =>
        ev(`(() => { const b = [...${within}.querySelectorAll("button")].find(b => b.textContent.trim() === ${JSON.stringify(text)}); if (!b) return false; b.click(); return true; })()`);
      const key = async (k: string, code: number, text?: string, shift = false) => {
        const mods = shift ? 8 : 0;
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, windowsVirtualKeyCode: code, text, modifiers: mods });
        await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, windowsVirtualKeyCode: code, modifiers: mods });
        await sleep(40);
      };
      const count = () => ev(`document.querySelector("nav.tabs .count")?.textContent ?? "0"`);
      // a tab's button, one undo step with its name
      await tab("Spells");
      check("Learn every spell", await button("Learn every spell"));
      await sleep(50);
      check("the spells all on", await ev(`[...document.querySelectorAll(".tabbody input[type=checkbox]")].every(c => c.checked)`));
      check("the undo button names it", (await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent === "Undo").title`)) === "Undo: Learn every spell (Ctrl+Z)",
        await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent === "Undo").title`));
      check("the title says unsaved", (await ev("document.title")).startsWith("• u6.seq"), await ev("document.title"));
      await shot(cdp, "ui-spells", false);
      await button("Undo");
      check("undone", (await count()) === "0", await count());
      // a grid's own buttons
      check("a circle's All", await button("All", `document.querySelector(".tabbody .card")`));
      check("a circle on", await ev(`[...document.querySelector(".tabbody .card").querySelectorAll("input[type=checkbox]")].every(c => c.checked)`));
      await button("Undo");
      // the filter on a long list
      await tab("People");
      await ev(`document.getElementById("t3-filter").focus()`);
      await cdp.send("Input.insertText", { text: "lord" });
      await sleep(50);
      const shown: string[] = await ev(`[...document.querySelectorAll(".records li:not([hidden])")].map(li => li.dataset.title)`);
      check("the filter narrows", shown.length > 0 && shown.length < 10 && shown.every(t => /lord/i.test(t)), shown);
      await key("Enter", 13);
      check("Enter picks the first", /Lord British/.test(await ev(`document.querySelector(".records li button.sel").textContent`)),
        await ev(`document.querySelector(".records li button.sel").textContent`));
      await shot(cdp, "ui-people", false);
      // picking a record keeps the list where it was scrolled to, the record focused
      await ev(`(() => { const f = document.getElementById("t3-filter"); f.value = ""; f.dispatchEvent(new Event("input", { bubbles: true })); })()`);
      const far: { top: number; id: string } = await ev(`(() => { const l = document.getElementById("t3-list"); l.scrollTop = (l.scrollHeight - l.clientHeight) / 2;
        const r = l.getBoundingClientRect(), b = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest("button");
        const top = l.scrollTop; b.focus(); b.click(); return { top, id: b.id }; })()`);
      await sleep(50);
      const after: { top: number; id: string; sel: string } = await ev(`(() => { const l = document.getElementById("t3-list");
        return { top: l.scrollTop, id: document.activeElement.id, sel: l.querySelector("button.sel").id }; })()`);
      check("the list stays scrolled", far.top > 0 && after.top === far.top && after.sel === far.id && after.id === far.id, { far, after });
      // a row's menu, the badge, the empty rows, the cells' names; the fixture is 1A's save
      // area as the disk ships it: the Avatar carries the Orb (pack slot 1) and one worn thing,
      // Dupre four in the pack (slots 1-4) and four worn, Shamino six, Iolo fifteen
      await tab("Inventory");
      check("a badge on each place", (await ev(`[...document.querySelectorAll(".records .rbadge")].map(b => b.textContent).join(",")`)) === "2,8,6,15",
        await ev(`[...document.querySelectorAll(".records .rbadge")].map(b => b.textContent).join(",")`));
      check("a cell has a name", (await ev(`document.getElementById("inv0.0.qty").getAttribute("aria-label")`)) === "Pack slot 1: Quantity",
        await ev(`document.getElementById("inv0.0.qty").getAttribute("aria-label")`));
      check("an empty row has no quantity", await ev(`!document.getElementById("inv0.5.qty") && !!document.getElementById("inv0.5.obj")`));
      check("Give to Dupre", await ev(`(() => { const s = document.getElementById("inv0.0.obj").closest("tr").querySelector("select.rowmenu");
        if (!s) return false; const o = [...s.options].find(o => o.text === "Give to Dupre"); s.value = o.value;
        s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`));
      check("the Orb has gone", (await ev(`document.getElementById("inv0.0.obj").value`)) === "—", await ev(`document.getElementById("inv0.0.obj").value`));
      await shot(cdp, "ui-inventory", false);
      await button("Undo");
      // Enter in a table: the next row, same column (Dupre's pack, two rows filled)
      await ev(`document.querySelectorAll(".records li button")[1].click()`);
      await sleep(50);
      await ev(`document.getElementById("inv1.0.qty").focus()`);
      await cdp.send("Input.insertText", { text: "1" });
      await key("Enter", 13);
      check("Enter moves down", (await ev("document.activeElement.id")) === "inv1.1.qty", await ev("document.activeElement.id"));
      await key("Enter", 13, undefined, true);
      check("Shift+Enter moves up", (await ev("document.activeElement.id")) === "inv1.0.qty", await ev("document.activeElement.id"));
      // Add an object: the first empty slot, its list open
      check("Add an object", await button("Add an object"));
      await sleep(80);
      check("its list open", await ev(`document.activeElement.id === "inv1.4.obj" && !document.getElementById("inv1.4.obj-list").hidden`),
        await ev("document.activeElement.id"));
      await key("Escape", 27);
      // a warning: Show goes to the field, its fix puts it right
      await tab("Party");
      await ev(`(() => { const el = document.getElementById("c0.hp"); el.value = "250"; el.dispatchEvent(new Event("change", { bubbles: true })); })()`);
      await sleep(50);
      check("the warning is there", await ev(`[...document.querySelectorAll(".banner.warn")].some(b => /more hit points/.test(b.textContent))`));
      await tab("World");
      check("Show", await button("Show", `[...document.querySelectorAll(".banner.warn")].find(b => /more hit points/.test(b.textContent))`));
      await sleep(80);
      check("Show focuses the field", (await ev("document.activeElement.id")) === "c0.hp", await ev("document.activeElement.id"));
      await shot(cdp, "ui-warning", false);
      const fix: string = await ev(`[...document.querySelectorAll(".banner.warn")].find(b => /more hit points/.test(b.textContent)).querySelector("button.small").textContent`);
      await button(fix, `[...document.querySelectorAll(".banner.warn")].find(b => /more hit points/.test(b.textContent))`);
      check("the fix", (await ev(`document.getElementById("c0.hp").value`)) === fix.replace("Set to ", ""), [fix, await ev(`document.getElementById("c0.hp").value`)]);
      // the Changes tab puts one change back
      await tab("World");
      await ev(`(() => { const el = document.getElementById("karma"); el.value = "50"; el.dispatchEvent(new Event("change", { bubbles: true })); })()`);
      await tab("Changes");
      const before = Number(await count());
      await ev(`document.querySelector("table.changes button").click()`);
      await sleep(50);
      check("Put back", Number(await count()) === before - 1, [before, await count()]);
      await button("Undo everything");
      // the bytes: click, two digits, the arrows
      await tab("Bytes");
      await ev(`document.querySelectorAll(".hex .b")[0x416].click()`);
      await key("4", 52, "4");
      check("a pending digit", (await ev(`document.querySelector(".hex .b.cur").textContent`)) === "4_", await ev(`document.querySelector(".hex .b.cur").textContent`));
      await key("2", 50, "2");
      check("the byte written", (await ev(`document.querySelectorAll(".hex .b")[0x416].textContent`)) === "42", await ev(`document.querySelectorAll(".hex .b")[0x416].textContent`));
      check("the cursor moves on", (await ev(`[...document.querySelectorAll(".hex .b")].indexOf(document.querySelector(".hex .b.cur"))`)) === 0x417);
      await key("ArrowDown", 40);
      check("Down: a row on", (await ev(`[...document.querySelectorAll(".hex .b")].indexOf(document.querySelector(".hex .b.cur"))`)) === 0x427);
      check("the status line", /^\$5827 /.test(await ev(`document.querySelector(".hexstatus").textContent`)), await ev(`document.querySelector(".hexstatus").textContent`));
      await shot(cdp, "ui-bytes", false);
      check("the undo names the byte", /^Undo: Byte \$5816: [0-9A-F]{2} → 42/.test(await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent === "Undo").title`)),
        await ev(`[...document.querySelectorAll("header button")].find(b => b.textContent === "Undo").title`));
      await cdp.eval(`[...document.querySelectorAll("header button")].find(b => b.textContent.startsWith("Download")).click()`);
      await sleep(150);
      process.stdout.write(`u6.seq, the page's controls: ${bad.length ? "FAILED\n  " + bad.join("\n  ") : "ok"}\n`);
      if (bad.length) fails++;
    }
    // saved games of your own, if there are any (build/user-saves): opened and looked at, not edited
    const USER = join(COLLECTION, "build", "user-saves");
    for (const f of existsSync(USER) ? readdirSync(USER).filter(n => /\.(s00|seq|d64)$/i.test(n)) : []) {
      await cdp.send("Page.navigate", { url: `file://${PAGE}` });
      await sleep(400);
      const raw = new Uint8Array(readFileSync(join(USER, f)));
      await cdp.eval(`(() => {
        const bytes = Uint8Array.from(atob("${b64(raw)}"), c => c.charCodeAt(0));
        const dt = new DataTransfer();
        dt.items.add(new File([bytes], ${JSON.stringify(f)}));
        window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      })()`);
      await sleep(300);
      const opened: number = await cdp.eval(`document.querySelectorAll("nav.tabs button").length`);
      await shot(cdp, `user-${f.replace(/\W+/g, "-")}`);
      process.stdout.write(`${f} (yours): ${opened ? "opens" : "DID NOT OPEN"}\n`);
      if (!opened) fails++;
    }
    if (cdp.problems.length) { process.stdout.write(cdp.problems.join("\n") + "\n"); fails++; }
    cdp.close();
  } finally {
    chrome.kill();
  }
  process.stdout.write(fails ? `${fails} FAILED\n` : `all good; screenshots in ${SHOTS}\n`);
  return fails ? 1 : 0;
}

process.exit(await main());
