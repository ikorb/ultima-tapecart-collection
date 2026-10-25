// The editor's page: open a file, edit the save in tabs, look at the bytes
// and the changes, and write the file back in the wrapper it came in.

import { h, hex2, hex4 } from "./dom.ts";
import { combo } from "./combo.ts";
import { open, serialise, savesOnDisk, gamesOnCart, OpenError, type Opened } from "../container/open.ts";
import { isD64 } from "../container/d64.ts";
import { isTcrt } from "../container/tcrt.ts";
import { viewOf, TITLES } from "../games/index.ts";
import {
  allFields, changes, invalid, maxLetters, beyond, beyondRules, withinRule, bulkValues,
  type Field, type GameView, type Section, type RecordDef, type Value, type Area, type Action,
  type Choice, type Warning, type Writer,
} from "../games/model.ts";

interface State {
  opened: Opened | null;
  view: GameView | null;
  tab: number;                         // index into view.tabs, then BYTES, CHANGES
  record: Map<string, number>;         // selected record per records section
  filter: Map<string, string>;         // the filter typed above a long record list
  hexArea: string;
  hexCursor: number | null;            // the byte the hex view edits
  hexNibble: number | null;            // its first digit, typed
  errors: Map<string, string>;         // field id -> why the typed value was refused
  message: { kind: "error" | "info"; text: string } | null;
  handle: FileSystemFileHandleLike | null;
  pick: Pick | null;
  after: (() => void)[];               // to do once the next render is on the page
}

/** A file holding several saves: a disk's save files, or a cart's six games. */
interface Pick {
  bytes: Uint8Array;
  name: string;
  title: string;
  items: { which: Uint8Array | number; label: string; detail: string }[];
  handle: FileSystemFileHandleLike | null;
}

// The File System Access API, where there is one (Chromium): save in place.
interface FileSystemFileHandleLike {
  name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<{ write(d: Uint8Array): Promise<void>; close(): Promise<void> }>;
}
type PickerWindow = Window & {
  showOpenFilePicker?: (o?: unknown) => Promise<FileSystemFileHandleLike[]>;
};

const st: State = {
  opened: null, view: null, tab: 0, record: new Map(), filter: new Map(), hexArea: "", hexCursor: null, hexNibble: null,
  errors: new Map(), message: null, handle: null, pick: null, after: [],
};

/** Enums with more choices than this get a searchable box instead of a plain dropdown. */
const COMBO_FROM = 24;
/** Record lists longer than this get a filter. */
const FILTER_FROM = 20;
const TITLE = "Ultima Tapecart Collection save editor";

let root: HTMLElement;

export function start(el: HTMLElement): void {
  root = el;
  window.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", e => { if (dirty()) e.preventDefault(); });
  window.addEventListener("dragover", e => { e.preventDefault(); document.body.classList.add("dragging"); });
  window.addEventListener("dragleave", e => { if (e.target === document.documentElement || e.clientX <= 0) document.body.classList.remove("dragging"); });
  window.addEventListener("drop", e => {
    e.preventDefault();
    document.body.classList.remove("dragging");
    const f = e.dataTransfer?.files[0];
    if (f) void readFile(f, null);
  });
  render();
}

function dirty(): boolean {
  return !!st.view && (changes(st.view).length > 0 || st.view.doc.changedBytes().size > 0);
}

// -- opening and saving ------------------------------------------------------------

async function pickFile(): Promise<void> {
  if (dirty() && !confirm("Discard the changes to the save that is open?")) return;
  const w = window as PickerWindow;
  if (w.showOpenFilePicker) {
    try {
      const [handle] = await w.showOpenFilePicker({ multiple: false });
      await readFile(await handle.getFile(), handle);
    } catch (e) {
      if ((e as Error).name !== "AbortError") fail(e);
    }
    return;
  }
  const input = h("input", { type: "file" });
  input.addEventListener("change", () => { const f = input.files?.[0]; if (f) void readFile(f, null); });
  input.click();
}

async function readFile(f: File, handle: FileSystemFileHandleLike | null): Promise<void> {
  const bytes = new Uint8Array(await f.arrayBuffer());
  try {
    if (isTcrt(bytes)) {
      const items = gamesOnCart(bytes).map(g => ({ which: g.game, label: TITLES[g.game - 1], detail: g.status }));
      st.pick = { bytes, name: f.name, title: `${f.name} is a cart: which game's save?`, items, handle };
      render();
      return;
    }
    if (isD64(bytes)) {
      const saves = savesOnDisk(bytes);
      if (saves.length > 1) {
        const items = saves.map(s => ({ which: s.raw, label: s.name,
          detail: `${s.game ? TITLES[s.game - 1] : "unknown game"}, ${s.type}` }));
        st.pick = { bytes, name: f.name, title: `${f.name} holds ${saves.length} saved games`, items, handle };
        render();
        return;
      }
    }
    show(open(bytes, f.name), handle);
  } catch (e) { fail(e); }
}

/** A file opened; `keep` (one just written back) keeps the place on the page. */
function show(o: Opened, handle: FileSystemFileHandleLike | null, message?: string, keep = false): void {
  st.opened = o;
  st.view = viewOf(o.save);
  if (!keep) {
    st.tab = 0;
    st.record = new Map();
    st.filter = new Map();
    st.hexCursor = null;
  }
  st.errors = new Map();
  st.hexNibble = null;
  if (!st.view.doc.areas.has(st.hexArea)) st.hexArea = [...st.view.doc.areas.keys()][0] ?? "";
  st.handle = handle;
  st.pick = null;
  st.message = message ? { kind: "info", text: message } : null;
  render();
}

function fail(e: unknown): void {
  const text = e instanceof OpenError ? e.message : `${(e as Error).message ?? e}`;
  st.message = { kind: "error", text: text.charAt(0).toUpperCase() + text.slice(1) + "." };
  render();
}

function output(): Uint8Array {
  if (!st.opened) throw new Error("nothing open");
  return serialise(st.opened);
}

async function saveInPlace(): Promise<void> {
  if (!st.handle || !st.opened) return download();
  try {
    const bytes = output();
    const w = await st.handle.createWritable();
    await w.write(bytes);
    await w.close();
    show(reopen(bytes), st.handle, `Saved to ${st.handle.name}.`, true);
  } catch (e) { fail(e); }
}

function download(): void {
  if (!st.opened) return;
  try {
    const bytes = output();
    const a = h("a", { href: URL.createObjectURL(new Blob([bytes as BlobPart])), download: st.opened.fileName });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    show(reopen(bytes), null, `Downloaded as ${st.opened.fileName}.`, true);
  } catch (e) { fail(e); }
}

/** The file just written, opened again: the new baseline for changes and undo. */
function reopen(bytes: Uint8Array): Opened {
  const o = st.opened!;
  const w = o.wrapper;
  return open(bytes, o.fileName, w.kind === "d64" ? w.entry : w.kind === "tcrt" ? w.game : undefined);
}

function onKey(e: KeyboardEvent): void {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod || !st.view) return;
  const k = e.key.toLowerCase();
  if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
  else if ((k === "z" && e.shiftKey) || k === "y") { e.preventDefault(); redo(); }
  else if (k === "s") { e.preventDefault(); void (st.handle ? saveInPlace() : download()); }
}

function undo(): void { st.view?.doc.undo(); st.errors.clear(); render(); }
function redo(): void { st.view?.doc.redo(); st.errors.clear(); render(); }

// -- editing -------------------------------------------------------------------------

function commit(f: Field, raw: Value): void {
  const v = st.view;
  if (!v) return;
  let value: Value = raw;
  if (f.enc.t !== "text" && f.enc.t !== "flag" && f.enc.t !== "nonzero") {
    const s = String(raw).trim();
    value = /^\$[0-9a-f]+$/i.test(s) ? parseInt(s.slice(1), 16) : s === "" ? NaN : Number(s);
  }
  const why = invalid(f, value);
  if (why) { st.errors.set(f.id, why); render(); return; }
  st.errors.delete(f.id);
  const before = v.doc.value(f);
  try { v.doc.set(f, value, `${names(v).get(f.id) ?? f.label}: ${shown(f, before)} → ${shown(f, value)}`); }
  catch (e) { st.errors.set(f.id, (e as Error).message); }
  render();
}

/** An edit of several fields (a button, a row's menu, a warning's fix) as one undo step. */
function run(label: string, fn: (w: Writer) => void): void {
  const v = st.view;
  if (!v) return;
  try { v.doc.edit(fn, label); } catch (e) { st.message = { kind: "error", text: (e as Error).message }; }
  st.errors.clear();
  render();
}

function runAction(v: GameView, a: Action): void {
  if (a.disabled?.(v.doc)) return;
  if (a.run) run(a.label, w => a.run!(w, v.doc));
  const id = a.focus?.(v.doc);
  if (id) goTo(v, id, true);
}

/** Every field's name for the change list and the undo button: the records
 *  it is in, a table's row, its label ("Iolo › Strength"). */
function names(v: GameView): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (secs: Section[], pre: string[]) => {
    for (const s of secs) {
      if (s.kind === "records") for (const r of s.records) walk(r.sections, [...pre, r.title(v.doc)]);
      else if (s.kind === "table")
        for (const row of s.rows) row.cells.forEach(f => f && out.set(f.id, [...pre, rowName(s.title, row.label), f.label].join(" › ")));
      else for (const f of s.fields) out.set(f.id, [...pre, f.label].join(" › "));
    }
  };
  for (const t of v.tabs) walk(t.sections, []);
  return out;
}

const rowName = (table: string, row: string) => /^\d+$/.test(row) ? `${table} slot ${row}` : row;

/** Shows a field: its tab, the records it is in, scrolled to, focused and
 *  flashed (or its list opened, for a searchable box). */
function goTo(v: GameView, id: string, openList = false): void {
  const find = (secs: Section[], key: string, recs: [string, number][]): [string, number][] | null => {
    for (const s of secs) {
      if (s.kind === "records") {
        for (const [k, r] of s.records.entries()) {
          const got = find(r.sections, `${key}.${r.key}`, [...recs, [key, k]]);
          if (got) return got;
        }
      } else if (s.fields.some(f => f.id === id)) return recs;
    }
    return null;
  };
  for (const [t, tab] of v.tabs.entries()) {
    const recs = find(tab.sections, `t${t}`, []);
    if (!recs) continue;
    st.tab = t;
    for (const [key, k] of recs) st.record.set(key, k);
    st.after.push(() => {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ block: "center" });
      el.focus({ preventScroll: true });
      if (openList && el.getAttribute("role") === "combobox") el.dispatchEvent(new Event("combo-open"));
      const row = el.closest(".field");
      row?.classList.add("flash");
      setTimeout(() => row?.classList.remove("flash"), 1600);
    });
    render();
    return;
  }
}

// -- rendering -----------------------------------------------------------------------

function render(): void {
  const focus = document.activeElement?.id;
  const scroll = window.scrollY;
  const lists = new Map([...document.querySelectorAll<HTMLElement>(".records .list[id]")].map(e => [e.id, e.scrollTop]));
  root.replaceChildren(header(), body());
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
  window.scrollTo(0, scroll);
  for (const e of document.querySelectorAll<HTMLElement>(".records .list[id]")) {
    e.scrollTop = lists.get(e.id) ?? 0;
    selectedInView(e);
  }
  document.title = st.opened ? `${dirty() ? "• " : ""}${st.opened.fileName} – ${TITLE}` : TITLE;
  const after = st.after;
  st.after = [];
  for (const f of after) f();
}

/** Scrolls a record list, and only the list, so that its selected record shows. */
function selectedInView(list: HTMLElement): void {
  const b = list.querySelector("button.sel");
  if (!b) return;
  const l = list.getBoundingClientRect(), r = b.getBoundingClientRect();
  if (r.top < l.top) list.scrollTop -= l.top - r.top;
  else if (r.bottom > l.bottom) list.scrollTop += r.bottom - l.bottom;
}

function header(): HTMLElement {
  const v = st.view, o = st.opened;
  const n = v ? changes(v).length : 0;
  const u = v?.doc.undoLabel(), r = v?.doc.redoLabel();
  return h("header", {},
    h("div", { class: "brand" }, h("span", { class: "logo" }, "Ultima"), " Tapecart Collection ", h("span", { class: "muted" }, "save editor")),
    o && v ? h("div", { class: "file" },
      h("span", { class: "game" }, v.title),
      h("span", { class: "name", title: wrapperText(o) }, o.fileName),
      h("span", { class: "muted small" }, wrapperText(o))) : h("div", { class: "file" }),
    h("div", { class: "actions" },
      h("button", { onclick: () => void pickFile() }, "Open…"),
      v && h("button", { onclick: undo, disabled: !u, title: u ? `Undo: ${u} (Ctrl+Z)` : "Nothing to undo" }, "Undo"),
      v && h("button", { onclick: redo, disabled: !r, title: r ? `Redo: ${r} (Ctrl+Shift+Z)` : "Nothing to redo" }, "Redo"),
      v && st.handle && h("button", { class: "primary", onclick: () => void saveInPlace(), disabled: !dirty(),
        title: `Write back to ${st.handle.name} (Ctrl+S)` }, n ? `Save (${n})` : "Save"),
      v && h("button", { class: st.handle ? "" : "primary", onclick: download, disabled: !dirty() && !!st.handle,
        title: "Download the edited file, in the same format as it was opened" },
        st.handle ? "Download" : n ? `Download (${n})` : "Download")));
}

function wrapperText(o: Opened): string {
  const w = o.wrapper;
  if (w.kind === "plain") return "the launcher's save file";
  if (w.kind === "pc64") return "in a PC64 wrapper";
  if (w.kind === "gamedisk") return `the game's ${w.disk.label} disk`;
  if (w.kind === "tcrt") return `${TITLES[w.game - 1]} on the cart`;
  return `on a disk image, as "${[...w.entry].map(c => String.fromCharCode(c)).join("")}"`;
}

function body(): HTMLElement {
  const parts: (HTMLElement | null)[] = [];
  if (st.message) parts.push(h("div", { class: `banner ${st.message.kind}`, role: st.message.kind === "error" ? "alert" : "status" },
    st.message.text, h("button", { class: "link", "aria-label": "Close", onclick: () => { st.message = null; render(); } }, "×")));
  if (st.pick) parts.push(picker());
  else if (!st.view) parts.push(welcome());
  else parts.push(editor(st.view));
  return h("main", {}, parts);
}

function welcome(): HTMLElement {
  return h("section", { class: "welcome" },
    h("div", { class: "drop", onclick: () => void pickFile() },
      h("div", { class: "big" }, "Drop a saved game here"),
      h("div", { class: "muted" }, "or click to pick a file")),
    h("div", { class: "cols" },
      h("div", {},
        h("h3", {}, "What it opens"),
        h("ul", {},
          h("li", {}, "The file the cart's launcher writes with ", h("b", {}, "E"), ", ", h("b", {}, "F"),
            ": ", h("code", {}, "ULTIMA I SAVE"), " … ", h("code", {}, "ULTIMA VI SAVE"), ", copied off the disk as it is"),
          h("li", {}, "The same in a PC64 wrapper (", h("code", {}, ".S00"), ", ", h("code", {}, ".P00"), ")"),
          h("li", {}, "A ", h("code", {}, ".d64"), " disk image holding one or more of them"),
          h("li", {}, "The cart itself, the ", h("code", {}, ".tcrt"), " an emulator plays: VICE keeps the saves in it"),
          h("li", {}, "Or the game's own disk with its save, as the original game or the launcher's ",
            h("b", {}, "E"), ", ", h("b", {}, "D"), " wrote it: Ultima I, Ultima II's Player disk, Ultima III's ",
            "Scenario, Ultima IV's Britannia, Ultima V's Britannia and Underworld, Ultima VI's Surface"))),
      h("div", {},
        h("h3", {}, "How it works"),
        h("ul", {},
          h("li", {}, "Everything happens in this page: the file never leaves your computer."),
          h("li", {}, "What the editor does not understand is kept byte for byte."),
          h("li", {}, "The edited file comes out in the format it went in; import it on the cart with ",
            h("b", {}, "I"), ", ", h("b", {}, "F"), ". A ", h("code", {}, ".tcrt"),
            " needs no import: the edit is already on the cart, where that import would have put it."),
          h("li", {}, "Fields marked ", h("span", { class: "badge ref" }, "ref"),
            " come from others' notes and are not yet checked against the game's code.")))));
}

function picker(): HTMLElement {
  const p = st.pick!;
  return h("section", { class: "card picker" },
    h("h2", {}, p.title),
    h("ul", {}, p.items.map(s => h("li", {},
      h("button", { onclick: () => { try { show(open(p.bytes, p.name, s.which), p.handle); } catch (e) { fail(e); } } },
        s.label), s.detail && " ", s.detail && h("span", { class: "muted" }, s.detail)))),
    h("button", { class: "link", onclick: () => { st.pick = null; render(); } }, "Cancel"));
}

function editor(v: GameView): HTMLElement {
  const tabs = [...v.tabs.map(t => t.title), "Bytes", "Changes"];
  const nChanges = changes(v).length;
  const tab = st.tab < v.tabs.length ? v.tabs[st.tab] : null;
  return h("div", { class: "editor" },
    [...(st.opened?.notes ?? []), ...v.remarks].map(r => h("div", { class: "banner note" }, r)),
    v.warnings().map(w => warning(v, w)),
    overLimits(v),
    v.readOnly && h("div", { class: "banner warn" }, v.readOnly),
    h("nav", { class: "tabs", role: "tablist" }, tabs.map((t, k) =>
      h("button", { class: k === st.tab ? "tab active" : "tab", role: "tab", "aria-selected": String(k === st.tab),
        onclick: () => { st.tab = k; render(); } },
        t, t === "Changes" && nChanges ? h("span", { class: "count", "aria-label": `, ${nChanges} changes` }, nChanges) : null))),
    tab ? h("div", { class: "tabbody", role: "tabpanel" },
          tab.actions?.length ? h("div", { class: "toolbar" }, tab.actions.map(a => actionButton(v, a))) : null,
          tab.sections.map(s => section(v, s, `t${st.tab}`)))
      : st.tab === v.tabs.length ? bytesTab(v) : changesTab(v));
}

function warning(v: GameView, w: Warning): HTMLElement {
  return h("div", { class: "banner warn" }, h("span", {}, w.text),
    h("span", { class: "fixes" },
      w.id && h("button", { class: "link", onclick: () => goTo(v, w.id!) }, "Show"),
      w.fix && h("button", { class: "small", disabled: !!w.fix.disabled, title: w.fix.disabled ?? undefined,
        onclick: () => run(`${w.fix!.label}: ${w.text.replace(/[.:].*$/, "")}`, w.fix!.run) }, w.fix.label)));
}

/** Values beyond the game's own limits: each with a way to it and to the limit. */
function overLimits(v: GameView): HTMLElement | null {
  const over = beyondRules(v);
  if (!over.length) return null;
  const nm = names(v);
  const list = h("ul", { class: "overlist" }, over.map(o => {
    const to = withinRule(o.field, o.value as number);
    const name = nm.get(o.field.id) ?? o.field.label;
    return h("li", {}, `${name}: ${o.value}`,
      h("span", { class: "muted small" }, ` (${o.field.rule!.text})`), " ",
      h("button", { class: "link", onclick: () => goTo(v, o.field.id) }, "Show"),
      h("button", { class: "small", onclick: () => run(`${name}: ${o.value} → ${to}`, w => w.set(o.field, to)) }, `Set to ${to}`));
  }));
  return h("div", { class: "banner warn over" },
    h("div", {},
      h("div", {}, `${over.length} value${over.length > 1 ? "s are" : " is"} beyond the game's own limits: `
        + `the game may put ${over.length > 1 ? "them" : "it"} back.`),
      over.length > 4 ? h("details", {}, h("summary", {}, `Show the ${over.length} values`), list) : list),
    over.length > 1 && h("button", { class: "small", onclick: () => run("Every value to the game's limits",
      w => over.forEach(o => w.set(o.field, withinRule(o.field, o.value as number)))) }, "Set all to the limits"));
}

function actionButton(v: GameView, a: Action, small = false): HTMLElement {
  const why = a.disabled?.(v.doc) ?? null;
  // aria-disabled, not disabled: a disabled button shows no tooltip saying why
  return h("button", { class: `act ${small ? "small" : ""} ${why ? "off" : ""}`, "aria-disabled": why ? "true" : undefined,
    title: why ? `${a.title ?? a.label} (${why})` : a.title, onclick: () => runAction(v, a) }, a.label);
}

/** A grid's "all" and "none" buttons. */
function bulkActions(v: GameView, s: Section): Action[] {
  const b = bulkValues(s);
  if (!b || s.kind !== "grid") return [];
  const set = (val: Value, label: string): Action => ({ label,
    title: `${s.title}: every one ${typeof val === "boolean" ? (val ? "on" : "off") : `to ${val}`}`,
    disabled: d => s.fields.every(f => !d.has(f) || d.value(f) === val) ? "already" : null,
    run: w => s.fields.forEach(f => { if (v.doc.has(f)) w.set(f, val); }) });
  return [set(b.all, b.allLabel), set(b.none, b.noneLabel)];
}

function sectionHead(v: GameView, s: Section, title: HTMLElement): HTMLElement {
  const acts = [...(s.actions ?? []), ...bulkActions(v, s)].map(a => {
    const b = actionButton(v, a, true);
    if (!a.focus) b.onclick = () => { if (!a.disabled?.(v.doc)) run(`${s.title}: ${a.label}`, w => a.run!(w, v.doc)); };
    return b;
  });
  return acts.length ? h("div", { class: "sec-head" }, title, h("div", { class: "sec-acts" }, acts)) : title;
}

function section(v: GameView, s: Section, key: string): HTMLElement {
  if (s.kind === "records") return records(v, s.title, s.records, s.note, key);
  if (s.kind === "table") return tableSection(v, s);
  // one source for the whole section: one badge on its title instead of one a field
  const srcs = new Set(s.fields.map(f => `${f.conf}|${f.src}`));
  const shared = srcs.size === 1 && s.fields.length > 1 ? s.fields[0] : null;
  const notes = new Set(s.fields.map(f => f.note ?? ""));
  const sharedNote = notes.size === 1 && s.fields.length > 1 ? s.fields[0].note : undefined;
  return h("section", { class: `card ${s.kind}` },
    sectionHead(v, s, h("h3", {}, s.title, shared && shared.conf === "reference" &&
      h("span", { class: "badge ref", title: `Source: ${shared.src} (not checked against the game's code)` }, "ref"))),
    (s.note || sharedNote) && h("p", { class: "muted small" }, [s.note, sharedNote].filter(Boolean).join(" ")),
    h("div", { class: s.kind === "grid" ? "grid-fields" : "form-fields" },
      s.fields.map(f => fieldRow(v, f, !!shared, !!sharedNote))));
}

function tableSection(v: GameView, s: Section & { kind: "table" }): HTMLElement {
  const menus = s.rows.some(r => r.menu);
  return h("section", { class: "card table" },
    sectionHead(v, s, h("h3", {}, s.title)),
    s.note && h("p", { class: "muted small" }, s.note),
    h("table", { class: "slots", onkeydown: (e: KeyboardEvent) => tableKey(e, s) },
      h("thead", {}, h("tr", {}, h("th", {}, ""), s.columns.map(c => h("th", { scope: "col" }, c)), menus && h("th", {}, ""))),
      h("tbody", {}, s.rows.map(r => {
        const empty = r.empty?.(v.doc) ?? false;
        const name = rowName(s.title, r.label);
        const choices = !empty && r.menu ? r.menu(v.doc) : [];
        return h("tr", { class: empty ? "empty" : "" }, h("th", { scope: "row" }, r.label),
          r.cells.map((f, j) => empty && j > 0 ? h("td", { class: "blank", "data-col": j })
            : h("td", { "data-col": j }, f && fieldRow(v, f, false, true, `${name}: ${s.columns[j]}`))),
          menus && h("td", {}, choices.length > 0 && rowMenu(name, choices)));
      }))));
}

function rowMenu(name: string, choices: Choice[], label = "Move…", aria = `Move what is in ${name}`): HTMLElement {
  return h("select", { class: "rowmenu", "aria-label": aria,
    onchange: (e: Event) => {
      const c = choices[Number((e.target as HTMLSelectElement).value)];
      if (c && !c.disabled) run(`${name}: ${c.label}`, c.run);
    } },
    h("option", { value: "", selected: true }, label),
    choices.map((c, k) => h("option", { value: String(k), disabled: !!c.disabled },
      c.disabled ? `${c.label} (${c.disabled})` : c.label)));
}

/** Enter and Shift+Enter in a table: the value taken, the same column a row down or up. */
function tableKey(e: KeyboardEvent, s: Section & { kind: "table" }): void {
  if (e.key !== "Enter" || e.altKey || e.ctrlKey || e.metaKey) return;
  const el = e.target;
  if (!(el instanceof HTMLInputElement)) return;
  const td = el.closest("td");
  const col = td?.getAttribute("data-col");
  if (!td || col === null || col === undefined) return;
  e.preventDefault();
  let tr: Element | null = td.parentElement, next: HTMLElement | null = null;
  while (!next && tr && (tr = e.shiftKey ? tr.previousElementSibling : tr.nextElementSibling))
    next = tr.querySelector(`td[data-col="${col}"] input`);
  const f = s.fields.find(x => x.id === el.id);
  if (f && el.getAttribute("role") !== "combobox") commit(f, el.value);
  if (f && st.errors.has(f.id)) return;
  if (next) document.getElementById(next.id)?.focus();
}

function records(v: GameView, title: string, recs: RecordDef[], note: string | undefined, key: string): HTMLElement {
  const sel = st.record.get(key) ?? Math.max(0, recs.findIndex(r => !r.present || r.present(v.doc)));
  const r = recs[sel];
  const filter = recs.length > FILTER_FROM ? (st.filter.get(key) ?? "") : null;
  const want = (filter ?? "").trim().toLowerCase();
  const list = h("ol", {}, recs.map((rec, k) => {
    const present = !rec.present || rec.present(v.doc);
    const touched = recordChanged(v, rec);
    const t = rec.title(v.doc);
    const badge = rec.badge?.(v.doc);
    return h("li", { hidden: !!want && !t.toLowerCase().includes(want), "data-title": t },
      h("button", { id: `${key}-rec-${k}`, class: `${k === sel ? "sel" : ""} ${present ? "" : "absent"}`, "aria-current": k === sel ? "true" : undefined,
        onclick: () => { st.record.set(key, k); render(); } },
        h("span", { class: "rt" }, t),
        h("span", { class: "rb" },
          badge && h("span", { class: "rbadge", title: badge.title }, badge.text),
          touched ? h("span", { class: "dot", title: "changed", "aria-label": "changed" }, "●") : null)));
  }));
  const none = h("p", { class: "muted small", hidden: [...list.children].some(li => !(li as HTMLElement).hidden) }, "None match.");
  return h("section", { class: "records" },
    h("aside", { class: "card list", id: `${key}-list` },
      h("h3", {}, title),
      note && h("p", { class: "muted small" }, note),
      filter !== null && h("input", { type: "search", id: `${key}-filter`, class: "filter", value: filter, placeholder: "Filter…",
        "aria-label": `Filter: ${title}`, autocomplete: "off", spellcheck: "false",
        oninput: (e: Event) => {
          const q = (e.target as HTMLInputElement).value;
          st.filter.set(key, q);
          const w = q.trim().toLowerCase();
          let any = false;
          for (const li of list.children) {
            const hide = !!w && !(li.getAttribute("data-title") ?? "").toLowerCase().includes(w);
            (li as HTMLElement).hidden = hide;
            any ||= !hide;
          }
          none.hidden = any;
        },
        onkeydown: (e: KeyboardEvent) => {
          const first = [...list.children].find(li => !(li as HTMLElement).hidden)?.querySelector("button");
          if (e.key === "Enter" && first) { e.preventDefault(); first.click(); }
          else if (e.key === "ArrowDown" && first) { e.preventDefault(); first.focus(); }
        } }),
      list, none),
    h("div", { class: "record" }, recordTools(v, r), r.empty?.(v.doc)
      ? h("section", { class: "card empty" }, h("h3", {}, r.title(v.doc)), h("p", {}, r.empty(v.doc)))
      : r.sections.map(s => section(v, s, `${key}.${r.key}`))));
}

/** A record's own edits: its menus (copy another one into it) and buttons (delete it). */
function recordTools(v: GameView, r: RecordDef): HTMLElement | null {
  if (!r.actions?.length && !r.menus?.length) return null;
  const name = r.title(v.doc);
  return h("div", { class: "toolbar" },
    (r.menus ?? []).map(m => rowMenu(name, m.choices(v.doc), m.label, `${m.label.replace(/…$/, "")}: ${name}`)),
    (r.actions ?? []).map(a => {
      const b = actionButton(v, a);
      b.onclick = () => { if (!a.disabled?.(v.doc)) run(`${name}: ${a.label}`, w => a.run!(w, v.doc)); };
      return b;
    }));
}

function recordChanged(v: GameView, rec: RecordDef): boolean {
  const walk = (secs: Section[]): boolean => secs.some(s => s.kind === "records" ? s.records.some(recordChanged.bind(null, v))
    : s.fields.some(f => v.doc.value(f) !== v.doc.originalValue(f)));
  return walk(rec.sections);
}

/** A field with its label, or bare (a table's cell: `bare` is then its accessible name). */
function fieldRow(v: GameView, f: Field, noBadge = false, noNote = false, bare?: string): HTMLElement {
  const present = v.doc.has(f);
  const val = present ? v.doc.value(f) : undefined;
  const changed = present && val !== v.doc.originalValue(f);
  const err = st.errors.get(f.id);
  const over = present && beyond(f, val);
  const a = v.doc.areas.get(f.area);
  const where = a ? `${a.label}: offset $${hex4(f.at)}` + (a.base ? `, address $${hex4(a.base + f.at)}` : "")
                  : "not in the file";
  const tip = `${where}\nSource: ${f.src}${f.conf === "reference" ? " (not checked against the game's code)" : ""}`;
  const badge = f.conf === "reference" && !noBadge ? h("span", { class: "badge ref", title: tip }, "ref") : null;
  const aria = { "aria-label": bare, "aria-invalid": err ? "true" : undefined, "aria-describedby": err || over ? `${f.id}-why` : undefined };
  let control: HTMLElement;
  if (!present) control = h("span", { class: "missing", title: "Not in the file: as on the game's original disk" }, "not in the file");
  else if (f.enc.t === "flag" || f.enc.t === "nonzero")
    control = h("input", { type: "checkbox", id: f.id, checked: !!val, disabled: f.readOnly, ...aria,
      onchange: (e: Event) => commit(f, (e.target as HTMLInputElement).checked) });
  else if (f.enc.t === "enum" && f.enc.values.length > COMBO_FROM)
    control = combo({ id: f.id, value: Number(val), values: f.enc.values, disabled: f.readOnly, label: bare,
      enterMoves: !!bare, pick: k => commit(f, k) });
  else if (f.enc.t === "enum") {
    const known = f.enc.values.some(([k]) => k === val);
    control = h("select", { id: f.id, disabled: f.readOnly, ...aria,
      onchange: (e: Event) => commit(f, Number((e.target as HTMLSelectElement).value)) },
      !known && h("option", { value: String(val), selected: true }, `unknown ($${hex2(Number(val))})`),
      f.enc.values.map(([k, label]) => h("option", { value: String(k), selected: k === val }, label)));
  } else if (f.enc.t === "text")
    control = h("input", { type: "text", id: f.id, value: String(val), maxlength: maxLetters(f.enc), disabled: f.readOnly,
      spellcheck: "false", autocomplete: "off", class: f.enc.upper ? "upper" : "", ...aria,
      onchange: (e: Event) => commit(f, (e.target as HTMLInputElement).value) });
  else {
    const bad = f.enc.t === "bcd" && !!a && !bcdShowable(a, f);
    control = h("input", { type: "text", inputmode: "numeric", id: f.id, value: bad ? "" : String(val),
      placeholder: bad ? "not a number" : "", disabled: f.readOnly, class: "num", ...aria,
      onfocus: bare ? (e: Event) => (e.target as HTMLInputElement).select() : undefined,
      onchange: (e: Event) => commit(f, (e.target as HTMLInputElement).value),
      onkeydown: (e: KeyboardEvent) => stepKey(e, f, val) });
  }
  return h("div", { class: `field ${changed ? "changed" : ""} ${err ? "invalid" : ""} ${over ? "beyond" : ""} ${f.readOnly ? "ro" : ""} ${bare ? "bare" : ""}`,
      title: bare ? `${f.label}\n${tip}` : tip },
    !bare && h("label", { for: f.id }, f.label, badge),
    h("div", { class: "control" }, control),
    changed && h("div", { class: "was", title: "as opened" }, `was ${shown(f, v.doc.originalValue(f))}`),
    err ? h("div", { class: "err", id: `${f.id}-why`, role: "alert" }, err)
      : over ? h("div", { class: "over", id: `${f.id}-why` }, `Beyond the game's limit: ${f.rule!.text}.`)
      : f.note && !noNote ? h("div", { class: "note" }, f.note) : null);
}

function bcdShowable(a: Area, f: Field): boolean {
  if (f.enc.t !== "bcd") return true;
  for (let k = 0; k < f.enc.n; k++) { const b = a.get(f.at + k); if ((b & 15) > 9 || b >> 4 > 9) return false; }
  return true;
}

function stepKey(e: KeyboardEvent, f: Field, val: Value | undefined): void {
  if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
  e.preventDefault();
  const n = Number(val) + (e.key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 10 : 1);
  if (!invalid(f, n)) commit(f, n);
}

function shown(f: Field, v: Value | undefined): string {
  if (v === undefined) return "—";
  if (f.enc.t === "enum") return f.enc.values.find(([k]) => k === v)?.[1] ?? `$${hex2(Number(v))}`;
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

// -- the bytes ------------------------------------------------------------------------

function bytesTab(v: GameView): HTMLElement {
  const areas = [...v.doc.areas.values()];
  const a = v.doc.areas.get(st.hexArea) ?? areas[0];
  const o = v.doc.original.get(a.key)!;
  const owner = new Map<number, string>();
  const nm = names(v);
  for (const { field } of allFields(v)) if (field.area === a.key)
    for (let k = 0; k < Math.max(1, sizeOf(field)); k++) owner.set(field.at + k, nm.get(field.id) ?? field.label);
  const cur = st.hexCursor !== null && st.hexCursor < a.length ? st.hexCursor : null;
  const rows: HTMLElement[] = [];
  for (let row = 0; row < a.length; row += 16) {
    const cells: HTMLElement[] = [];
    let text = "";
    for (let i = row; i < Math.min(row + 16, a.length); i++) {
      const pick = () => { st.hexCursor = i; st.hexNibble = null; st.after.push(focusHex); render(); };
      if (!a.has(i)) { cells.push(h("span", { class: `b gone ${i === cur ? "cur" : ""}`, title: "not in the file", onclick: pick }, "··")); text += " "; continue; }
      const b = a.get(i), was = o[i];
      const cls = `b ${b !== was ? "chg" : ""} ${owner.has(i) ? "known" : ""} ${i === cur ? "cur" : ""}`;
      cells.push(h("span", { class: cls, onclick: pick,
        title: `${owner.get(i) ?? "not decoded"}\noffset $${hex4(i)}${a.base ? `, $${hex4(a.base + i)}` : ""}${b !== was ? `\nwas $${hex2(was)}` : ""}` },
        i === cur && st.hexNibble !== null ? `${st.hexNibble.toString(16).toUpperCase()}_` : hex2(b)));
      const c = b & 0x7f;
      text += c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : "·";
    }
    rows.push(h("div", { class: "hexrow" }, h("span", { class: "addr" }, hex4(a.base + row)), cells, h("span", { class: "asc" }, text)));
  }
  const status = cur === null ? "Click a byte, then type two hex digits; the arrows move, Escape stops."
    : `$${hex4(a.base + cur)} (offset $${hex4(cur)}): ${a.has(cur) ? hex2(a.get(cur)) : "not in the file"}`
      + `${a.has(cur) && a.get(cur) !== o[cur] ? `, was ${hex2(o[cur])}` : ""} · ${owner.get(cur) ?? "not decoded"}`;
  return h("section", { class: "card bytes" },
    h("div", { class: "bytes-head" },
      h("select", { "aria-label": "Which bytes", onchange: (e: Event) => {
        st.hexArea = (e.target as HTMLSelectElement).value; st.hexCursor = null; st.hexNibble = null; render(); } },
        areas.map(x => h("option", { value: x.key, selected: x.key === a.key }, x.label))),
      h("span", { class: "muted small" }, "Bright bytes belong to a field; changed ones are marked.")),
    h("div", { class: "hexstatus small", "aria-live": "polite" }, status),
    h("div", { class: "hex", id: "hex", tabindex: 0, "aria-label": "The bytes: the arrows move, two hex digits change a byte",
      onkeydown: (e: KeyboardEvent) => hexKey(e, v, a) }, rows));
}

function focusHex(): void {
  document.getElementById("hex")?.focus({ preventScroll: true });
  document.querySelector(".hex .b.cur")?.scrollIntoView({ block: "nearest" });
}

function hexKey(e: KeyboardEvent, v: GameView, a: Area): void {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const i = st.hexCursor ?? 0;
  const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -16, ArrowDown: 16, PageUp: -256, PageDown: 256,
    Home: -(i % 16), End: 15 - i % 16 };
  if (e.key in moves) {
    st.hexCursor = Math.max(0, Math.min(a.length - 1, st.hexCursor === null ? 0 : i + moves[e.key]));
    st.hexNibble = null;
  } else if (e.key === "Escape") {
    if (st.hexNibble !== null) st.hexNibble = null; else st.hexCursor = null;
  } else if (e.key === "Backspace") st.hexNibble = null;
  else if (/^[0-9a-f]$/i.test(e.key) && st.hexCursor !== null && a.has(i)) {
    const d = parseInt(e.key, 16);
    if (st.hexNibble === null) st.hexNibble = d;
    else {
      const val = st.hexNibble << 4 | d, old = a.get(i);
      st.hexNibble = null;
      v.doc.edit(w => w.setByte(a.key, i, val), `Byte $${hex4(a.base + i)}: ${hex2(old)} → ${hex2(val)}`);
      st.hexCursor = Math.min(a.length - 1, i + 1);
    }
  } else return;
  e.preventDefault();
  st.after.push(focusHex);
  render();
}

function sizeOf(f: Field): number {
  return f.enc.t === "u16le" ? 2 : f.enc.t === "bcd" || f.enc.t === "text" ? f.enc.n : 1;
}

// -- the changes ----------------------------------------------------------------------

function changesTab(v: GameView): HTMLElement {
  const list = changes(v);
  const nm = names(v);
  const bytes = v.doc.changedBytes();
  const fieldBytes = new Set<string>();
  for (const { field } of allFields(v)) for (let k = 0; k < sizeOf(field); k++) fieldBytes.add(`${field.area}:${field.at + k}`);
  const loose = [...bytes].flatMap(([area, at]) => at.filter(i => !fieldBytes.has(`${area}:${i}`)).map(i => [area, i] as [string, number]));
  const back = (c: (typeof list)[number]) => {
    v.doc.revert(c.field, `${nm.get(c.field.id) ?? c.field.label}: back to ${shown(c.field, c.before)}`);
    st.errors.clear();
    render();
  };
  return h("section", { class: "card" },
    h("h3", {}, list.length || loose.length ? "What changes when you save" : "Nothing changed yet"),
    list.length > 0 && h("table", { class: "changes" },
      h("thead", {}, h("tr", {}, h("th", {}, "Where"), h("th", {}, "Field"), h("th", {}, "Was"), h("th", {}, "Now"), h("th", {}, ""))),
      h("tbody", {}, list.map(c => h("tr", {},
        h("td", { class: "muted" }, c.path), h("td", {}, c.field.label),
        h("td", {}, shown(c.field, c.before)), h("td", { class: "now" }, shown(c.field, c.after)),
        h("td", {}, h("button", { class: "small", title: `Put back ${shown(c.field, c.before)}`,
          "aria-label": `Put back ${nm.get(c.field.id) ?? c.field.label} as opened`, onclick: () => back(c) }, "Put back")))))),
    loose.length > 0 && h("p", {}, `${loose.length} byte${loose.length > 1 ? "s" : ""} changed outside the known fields (Bytes tab): `,
      loose.slice(0, 12).map(([area, i]) => `${area} $${hex4(i)}`).join(", "), loose.length > 12 ? " … " : " ",
      h("button", { class: "small", onclick: () => { v.doc.revertBytes(loose, `${loose.length} byte${loose.length > 1 ? "s" : ""} as opened`); render(); } },
        "Put them back")),
    (list.length > 0 || loose.length > 0) && h("button", { onclick: () => {
      if (!confirm("Undo every change?")) return;
      while (v.doc.canUndo()) v.doc.undo();
      st.errors.clear();
      render();
    } }, "Undo everything"));
}
