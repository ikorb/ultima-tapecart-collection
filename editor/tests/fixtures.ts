// The golden files editor/make_fixtures.py writes from the launcher's own
// export path, and the games' disks for cross-checks: the stand-ins `make
// disks` writes (build/disks/<key>.d64, the keys of ultima/disks/keys.py).

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const COLLECTION = join(import.meta.dirname, "..", "..");
export const FIXTURES = join(COLLECTION, "build", "editor-fixtures");
export const GAMES = ["u1", "u2", "u3", "u4", "u5", "u6"];

export function have(name: string): boolean {
  return existsSync(join(FIXTURES, name));
}

export function fixture(name: string): Uint8Array {
  return new Uint8Array(readFileSync(join(FIXTURES, name)));
}

export const NO_FIXTURES = existsSync(join(FIXTURES, "u1.seq")) ? false
  : "no build/editor-fixtures (run ../.venv/bin/python editor/make_fixtures.py)";

/** A game's disk by its key ("u4c"), as `make disks` assembled it. */
export function original(key: string): Uint8Array | null {
  const p = join(COLLECTION, "build", "disks", key + ".d64");
  return existsSync(p) ? new Uint8Array(readFileSync(p)) : null;
}
