// A searchable dropdown for enums with many choices (Ultima VI's 158 objects,
// Ultima V's 49 things to ready): a text box that shows the choice, and a
// list that narrows as you type.
//
// Typing filters (the words' starts first, then anywhere; "$1F" or "#31" by
// the byte); Up/Down move, Enter or a click picks, Escape puts the text back,
// Tab picks what is highlighted if something was typed.  The list opens on
// typing, a click or Alt+Down -- not on focus, because the page re-renders
// after every edit and puts the focus back (a "combo-open" event opens it
// from outside: the "Add an object" button).  An empty box and Enter picks
// the "nothing" choice, where there is one.  In a table (enterMoves), Enter
// with the list closed is left to the table: the next row.

import { h, hex2 } from "./dom.ts";

export interface ComboOptions {
  id: string;
  value: number;
  values: [number, string][];
  disabled?: boolean;
  /** The accessible name, where no <label> names the box. */
  label?: string;
  enterMoves?: boolean;
  pick: (k: number) => void;
}

const EMPTY = new Set(["—", "(nothing)", "(none)", "none", "nothing"]);
const words = (label: string) => EMPTY.has(label) ? `${label} empty nothing none` : label;

/** The choices that match `q`, best first: word starts, then substrings. */
export function matches(values: [number, string][], q: string): [number, string][] {
  const s = q.trim().toLowerCase();
  if (!s) return values;
  const code = /^(?:\$([0-9a-f]{1,2})|#(\d{1,3}))$/.exec(s);
  if (code) {
    const n = code[1] !== undefined ? parseInt(code[1], 16) : Number(code[2]);
    return values.filter(([k]) => k === n);
  }
  const start: [number, string][] = [], inside: [number, string][] = [];
  for (const v of values) {
    const w = words(v[1]).toLowerCase();
    const at = w.indexOf(s);
    if (at < 0) continue;
    (at === 0 || /[\s(/-]/.test(w[at - 1]) ? start : inside).push(v);
  }
  return [...start, ...inside];
}

export function combo(o: ComboOptions): HTMLElement {
  const label = (k: number) => o.values.find(([v]) => v === k)?.[1] ?? `unknown ($${hex2(k)})`;
  const listId = `${o.id}-list`;
  const input = h("input", {
    type: "text", id: o.id, value: label(o.value), disabled: o.disabled, autocomplete: "off", spellcheck: "false",
    role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false", "aria-controls": listId,
    "aria-label": o.label,
  });
  const list = h("ul", { id: listId, role: "listbox", class: "combo-list", hidden: true });
  const box = h("div", { class: "combo" }, input, list);
  let shown: [number, string][] = [];
  let at = -1;                                        // the highlighted entry of `shown`
  let typed = false;

  function fill(q: string): void {
    shown = matches(o.values, q);
    at = typed ? (shown.length ? 0 : -1) : shown.findIndex(([k]) => k === o.value);
    const s = q.trim().toLowerCase();
    list.replaceChildren(...shown.map(([k, text], j) => {
      const hit = typed && s && !s.startsWith("$") && !s.startsWith("#") ? text.toLowerCase().indexOf(s) : -1;
      return h("li", { id: `${listId}-${j}`, role: "option", "aria-selected": String(j === at),
          class: `${j === at ? "hi" : ""} ${k === o.value ? "cur" : ""}`,
          onmousedown: (e: Event) => e.preventDefault(),         // keep the focus (and the blur away)
          onclick: () => choose(k) },
        h("span", {}, hit < 0 ? text : [text.slice(0, hit), h("mark", {}, text.slice(hit, hit + s.length)), text.slice(hit + s.length)]),
        h("span", { class: "code" }, `$${hex2(k)}`));
    }));
    if (!shown.length) list.append(h("li", { class: "none" }, "No match"));
    mark();
  }

  function mark(): void {
    [...list.children].forEach((li, j) => {
      li.classList.toggle("hi", j === at);
      if (li.getAttribute("role") === "option") li.setAttribute("aria-selected", String(j === at));
    });
    if (at >= 0) {
      input.setAttribute("aria-activedescendant", `${listId}-${at}`);
      (list.children[at] as HTMLElement).scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  }

  function openList(q: string): void {
    fill(q);
    if (list.hidden) {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      const r = input.getBoundingClientRect();         // above, if there is no room below
      box.classList.toggle("up", r.bottom + 300 > window.innerHeight && r.top > window.innerHeight - r.bottom);
      mark();
    }
  }

  function close(): void {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    typed = false;
  }

  function revert(): void {
    close();
    input.value = label(o.value);
  }

  function choose(k: number): void {
    close();
    input.value = label(k);
    if (k !== o.value) o.pick(k);
  }

  function move(by: number): void {
    if (list.hidden) { openList(typed ? input.value : ""); return; }
    if (!shown.length) return;
    at = Math.max(0, Math.min(shown.length - 1, (at < 0 ? (by > 0 ? -1 : shown.length) : at) + by));
    mark();
  }

  input.addEventListener("focus", () => input.select());
  input.addEventListener("combo-open", () => { input.select(); openList(""); });
  input.addEventListener("click", () => { if (list.hidden) { input.select(); openList(""); } });
  input.addEventListener("input", () => { typed = true; openList(input.value); });
  input.addEventListener("blur", revert);
  input.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "PageDown") { e.preventDefault(); move(8); }
    else if (e.key === "PageUp") { e.preventDefault(); move(-8); }
    else if (e.key === "Escape") { if (!list.hidden || typed) { e.preventDefault(); e.stopPropagation(); revert(); input.select(); } }
    else if (e.key === "Enter") {
      const empty = input.value.trim() === "" ? o.values.find(([, t]) => EMPTY.has(t)) : undefined;
      if (list.hidden && !empty && o.enterMoves && !typed) return;          // the table's: the next row
      e.preventDefault();
      e.stopPropagation();
      if (empty) choose(empty[0]);
      else if (!list.hidden && at >= 0) choose(shown[at][0]);
      else if (list.hidden) openList("");
      else revert();
    } else if (e.key === "Tab") {
      if (typed && at >= 0) choose(shown[at][0]); else revert();
    }
  });
  return box;
}
