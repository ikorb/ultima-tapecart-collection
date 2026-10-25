// A game's view of a decoded save file.

import type { Ucsv } from "../container/ucsv.ts";
import type { GameView } from "./model.ts";
import { view as u1 } from "./u1.ts";
import { view as u2 } from "./u2.ts";
import { view as u3 } from "./u3.ts";
import { view as u4 } from "./u4.ts";
import { view as u5 } from "./u5.ts";
import { view as u6 } from "./u6.ts";

const VIEWS = [u1, u2, u3, u4, u5, u6];

export function viewOf(save: Ucsv): GameView {
  return VIEWS[save.game - 1](save);
}

export const TITLES = ["Ultima I", "Ultima II", "Ultima III", "Ultima IV", "Ultima V", "Ultima VI"];
