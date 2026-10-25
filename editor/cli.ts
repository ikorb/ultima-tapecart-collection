// The editor without the page, for scripts and the host tests:
//
//   node editor/cli.ts show FILE                 every field: id, value, where
//   node editor/cli.ts set FILE OUT id=value...  edit and write OUT (same wrapper)
//
// FILE may be a save file, a PC64 file or a .d64 holding one (for a disk
// with several, add --file="ULTIMA IV SAVE"), or a cart image (.tcrt, with
// --game=1..6).

import { readFileSync, writeFileSync } from "node:fs";
import { basename } from "node:path";
import { open, serialise } from "./src/container/open.ts";
import { viewOf } from "./src/games/index.ts";
import { allFields, changes } from "./src/games/model.ts";

function load(path: string, which?: string, game?: string) {
  const bytes = new Uint8Array(readFileSync(path));
  const pick = game ? Number(game) : which ? Uint8Array.from([...which].map(c => c.charCodeAt(0))) : undefined;
  const o = open(bytes, basename(path), pick);
  return { o, v: viewOf(o.save) };
}

function main(argv: string[]): number {
  const opt = argv.find(a => a.startsWith("--file="))?.slice(7);
  const game = argv.find(a => a.startsWith("--game="))?.slice(7);
  const args = argv.filter(a => !a.startsWith("--"));
  const [cmd, file, ...rest] = args;
  if (cmd === "show" && file) {
    const { v } = load(file, opt, game);
    process.stdout.write(`${v.title}\n`);
    for (const r of v.remarks) process.stdout.write(`  note: ${r}\n`);
    for (const { path, field } of allFields(v)) {
      const val = v.doc.value(field);
      process.stdout.write(`${field.id.padEnd(16)} ${String(val ?? "(not in the file)").padEnd(12)} ${path} › ${field.label}\n`);
    }
    return 0;
  }
  if (cmd === "set" && file && rest.length >= 1) {
    const [out, ...edits] = rest;
    const { o, v } = load(file, opt, game);
    const fields = new Map(allFields(v).map(x => [x.field.id, x.field]));
    for (const e of edits) {
      const m = /^([^=]+)=(.*)$/.exec(e);
      if (!m) throw new Error(`not id=value: ${e}`);
      const f = fields.get(m[1]);
      if (!f) throw new Error(`no field ${m[1]} in ${v.title}`);
      const raw = m[2];
      const value = f.enc.t === "text" ? raw : f.enc.t === "flag" || f.enc.t === "nonzero" ? raw === "1" || raw === "true"
        : /^\$/.test(raw) ? parseInt(raw.slice(1), 16) : Number(raw);
      v.doc.set(f, value);
    }
    writeFileSync(out, serialise(o));
    for (const c of changes(v)) process.stdout.write(`${c.field.id}: ${String(c.before)} -> ${String(c.after)}\n`);
    for (const w of v.warnings()) process.stdout.write(`warning: ${w.text}\n`);
    return 0;
  }
  process.stderr.write("usage: node cli.ts show FILE | set FILE OUT id=value ... [--file=NAME] [--game=N]\n");
  return 2;
}

try {
  process.exit(main(process.argv.slice(2)));
} catch (e) {
  process.stderr.write(`${(e as Error).message}\n`);
  process.exit(1);
}
