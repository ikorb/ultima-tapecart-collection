// What a picked file is, and how to write the edited save back into the
// same kind of file: a plain save file, the same in a PC64 wrapper, a .d64
// holding one (or more), a game's own disk, or the cart itself (.tcrt).

import * as ucsv from "./ucsv.ts";
import * as pc64 from "./pc64.ts";
import { D64, isD64, nameText, type DirEntry } from "./d64.ts";
import { recognise, readSave, writeSave, type GameDisk } from "./gamedisks.ts";
import * as tcrt from "./tcrt.ts";
import { prepare, readCart, writeCart, status, CartError, type Prepared } from "./cart.ts";

export type Wrapper =
  | { kind: "plain" }
  | { kind: "pc64"; name: Uint8Array; recordSize: number }
  | { kind: "d64"; image: Uint8Array; entry: Uint8Array }
  | { kind: "gamedisk"; image: Uint8Array; disk: GameDisk; before: ucsv.Ucsv }
  | { kind: "tcrt"; image: tcrt.Tcrt; cart: Prepared; game: number; before: ucsv.Ucsv };

export interface Opened {
  save: ucsv.Ucsv;
  wrapper: Wrapper;
  fileName: string;
  original: Uint8Array;        // the save file's own bytes as read
  notes: string[];             // about the file as a whole (another release's disk ...)
}

export interface DiskSave { name: string; raw: Uint8Array; game: number | null; type: string }

export class OpenError extends Error {}

/** The save files on a disk: every file that starts "UCSV", whatever its name. */
export function savesOnDisk(image: Uint8Array): DiskSave[] {
  const d = new D64(image);
  const out: DiskSave[] = [];
  for (const e of d.files()) {
    let data: Uint8Array;
    try { data = d.read(e); } catch { continue; }
    if (ucsv.isUcsv(data))
      out.push({ name: nameText(e.name), raw: e.name, game: data[4] >= 1 && data[4] <= 6 ? data[4] : null,
                 type: ["DEL", "SEQ", "PRG", "USR", "REL"][e.type & 7] ?? "?" });
  }
  return out;
}

export interface CartGame { game: number; status: string }

const CART_TITLES = ["", "Ultima I", "Ultima II", "Ultima III", "Ultima IV", "Ultima V", "Ultima VI"];

/** The games on a cart, for a pick: every one of the six, and what can be
 *  told of its save. */
export function gamesOnCart(bytes: Uint8Array): CartGame[] {
  const cart = openCart(bytes).cart;
  return [1, 2, 3, 4, 5, 6].map(game => ({ game, status: status(cart, game) }));
}

function openCart(bytes: Uint8Array): { image: tcrt.Tcrt; cart: Prepared } {
  try {
    const image = tcrt.parse(bytes);
    return { image, cart: prepare(image.flash) };
  } catch (e) {
    if (e instanceof tcrt.TcrtError || e instanceof CartError) throw new OpenError(e.message);
    throw e;
  }
}

/** Opens a picked file.  For a disk with several save files, `which` names
 *  the one (DiskSave.raw); without it the only one is taken.  For a cart it
 *  is the game, 1-6. */
export function open(bytes: Uint8Array, fileName: string, which?: Uint8Array | number): Opened {
  if (tcrt.isTcrt(bytes)) {
    if (typeof which !== "number" || which < 1 || which > 6) throw new OpenError("the cart holds six games: pick one");
    const { image, cart } = openCart(bytes);
    let save: ucsv.Ucsv;
    try { save = readCart(cart, which); } catch (e) { throw new OpenError((e as Error).message); }
    const notes = [...cart.notes, `${CART_TITLES[which]}'s save on the cart: only it is changed. VICE writes the cart `
      + "back to this file when it quits, so quit VICE (or detach the cart) before saving here, and attach it again after."];
    return { save, original: ucsv.encode(save), fileName, notes,
             wrapper: { kind: "tcrt", image, cart, game: which, before: ucsv.decode(ucsv.encode(save)) } };
  }
  if (typeof which === "number") throw new OpenError("not a cart image");
  if (pc64.isPc64(bytes)) {
    const p = pc64.unwrap(bytes);
    return { save: decode(p.data), original: p.data, fileName, notes: [],
             wrapper: { kind: "pc64", name: p.name, recordSize: p.recordSize } };
  }
  if (ucsv.isUcsv(bytes))
    return { save: decode(bytes), original: bytes, fileName, notes: [], wrapper: { kind: "plain" } };
  if (isD64(bytes)) {
    const saves = savesOnDisk(bytes);
    if (saves.length === 0) {
      const r = recognise(bytes);
      if (!r) throw new OpenError("this disk holds no saved game file of the collection, and is none of the games' disks that hold a save");
      let save: ucsv.Ucsv;
      try { save = readSave(bytes, r.disk); } catch (e) { throw new OpenError((e as Error).message); }
      const notes = [`The game's own ${r.disk.label} disk: the save is edited where the original game keeps it.`];
      if (!r.original) notes.push(`The cart's launcher would not take it for its own import: its name ("${r.diskName}") `
        + "or the disk's own number is not quite an original's.");
      const other = save.slots.map((s, k) => s ? -1 : k).filter(k => k >= 0 && r.disk.game === 5);
      if (other.length) notes.push(`The ${r.disk.first ? "Britannia (2A)" : "Underworld (2B)"} disk holds the rest of this save.`);
      if (r.disk.game === 6) notes.push("Only the save area is edited; the chunk files on the disk stay as they are.");
      return { save, original: ucsv.encode(save), fileName, notes,
               wrapper: { kind: "gamedisk", image: bytes.slice(), disk: r.disk, before: ucsv.decode(ucsv.encode(save)) } };
    }
    let pick = saves[0];
    if (which) {
      const hit = saves.find(s => s.raw.length === which.length && s.raw.every((v, i) => v === which[i]));
      if (!hit) throw new OpenError("no such file on the disk");
      pick = hit;
    } else if (saves.length > 1) throw new OpenError("this disk holds several saved game files: pick one");
    const d = new D64(bytes);
    const data = d.read(d.find(pick.raw) as DirEntry);
    return { save: decode(data), original: data, fileName, notes: [],
             wrapper: { kind: "d64", image: bytes.slice(), entry: pick.raw } };
  }
  throw new OpenError("not a saved game file of the collection, a PC64 file, a .d64 or a .tcrt");
}

function decode(b: Uint8Array): ucsv.Ucsv {
  try { return ucsv.decode(b); }
  catch (e) { throw new OpenError((e as Error).message); }
}

/** The file to write: the save encoded, in the wrapper it came in. */
export function serialise(o: Opened, save: ucsv.Ucsv = o.save): Uint8Array {
  const w = o.wrapper;
  if (w.kind === "gamedisk") return writeSave(w.image, w.disk, save, w.before);
  if (w.kind === "tcrt") {
    try { return tcrt.pack(w.image, writeCart(w.cart, save, w.before)); }
    catch (e) { throw e instanceof CartError ? new OpenError(e.message) : e; }
  }
  const data = ucsv.encode(save);
  if (w.kind === "plain") return data;
  if (w.kind === "pc64") return pc64.wrap(w.name, data, w.recordSize);
  const d = new D64(w.image);
  const e = d.find(w.entry);
  if (!e) throw new OpenError("the file is no longer on the disk");
  d.rewrite(e, data);
  return d.data;
}

/** The game's file name ("ULTIMA IV SAVE"), as the page writes it. */
export function defaultName(game: number): string {
  return ucsv.NAMES[game];
}
