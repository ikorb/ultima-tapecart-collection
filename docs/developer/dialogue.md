# Dialogue as text

`make dialogue` writes every game's dialogue as plain text into `build/dialogue/<game>/`,
from your own disks (U4 also from the cart as built). The code is in
`ultima/dialogue/`; each script's docstring says how its game stores and picks its text,
and each runs alone as `python -m ultima.dialogue.<script> [--out DIR]`.
`tests/test_dialogue.py` runs U1-U5's.

- **`u1talk.py`**: U1 has no Talk command and no conversation files. Kings and shops
  answer Transact, the pub's keeper a drink; the text is inline strings (`JSR
  $848E`/`$848A`) in the overlays `TW`, `CA`, `OU`, `TM`, `SP`, `DN` and in `MI`'s
  tables. The kings' quests by castle (`CA` `$8CB7`), the princesses, the eight rumours
  (`TW` `$ADEA`).
- **`u2talk.py`**: a person's `MON` byte `+$A0` of `$81` or above is string n of the
  place's `TLK` file (`ULTIMA` `$8230`, `$5B1C`); otherwise the tile's fixed line (`$6C`,
  the king's tribute). Eras from the time door's sign (`$8E13`: 0 Legends, 1 9,000,000
  B.C., 2 300 B.C., 3 1990 A.D., 4 2112 A.D.), planets from `STARS`. No place has a name
  in the game.
- **`u3talk.py`**: from the original disks, not the cart (whose `ULT3` is Ultima III
  Gold's), through the game's own catalog. T(ransact) (`ULT3` `$6676`): `MON` flags &
  `$0F` picks `TLKx` entry n (0 the default greeting), tile `$4C` Lord British; across a
  counter `SHP<party y & 7>`; a dungeon's "misty writing" is `TLK` entry level+1. **`CONx`
  are combat maps**, and `FNTN`/`TIME`/`BRND`/`SHRN` hold no text. Its `PLACES` names
  Sosaria's entrances for the maps.
- **`u4talk.py [--cart]`**: a person's byte `+$4E0` n -> disk B block 16 x (location - 1)
  + n (game main `$59CE`); the page's last bytes: `$FC` the question's trigger, `$FE`
  humility, `$FF` the turn-away chance. Lord British (chunk `$87`) through his 28-keyword
  jump table, HELP (`$88`) as its nine hints. `--cart` reads the cart as built, with
  Ultima IV Remastered's mixed case and content fixes, which is what a player of the cart
  sees. Isaac (Skara Brae 16) is on no map: the inn's chunk `$73` places him.
- **`u5talk.py`**: the people tables are `$6C30` records `$F8 + (place-1 & 7)`
  (`main.twn` `$995D`); a talk byte of 1-`$7F` is a conversation (record `$F0 - n`, 512
  bytes Huffman-coded, decoder `T` `$AC56`), `$81-$88` a shop overlay (`TALK.xx`), `$FF` a
  guard. 135 conversations; the PC version's control codes mostly survive; there is no
  word dictionary.
- **`u6_dialogue.py`**: the conversations of the three Populace disks. Each file `tNNN`
  is one person's script: `FF NN`, the name, `F1` and the look description, `F2` and the
  script. The bytecode is the PC version's (the opcode names follow Nuvie's
  `ConverseInterpret`), with two C64 differences: the text is in the game's own character
  set, and jump targets and the `D2`/`D4` literals are 16-bit.
