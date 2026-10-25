# The Ultima Collection for the tapecart: Ultima I-VI on one 2 MiB cart.
#
#   make                 the tapecart and the EasyFlash cart (make cart, make ef)
#   make all             both carts, the editor, the maps and the dialogue
#   make cart            the tapecart: build/ultima-collection.tcrt (full image) and
#                        build/ultima-collection-update.bin (keeps the saves)
#   make import          the cart with the saved games found on your disks in it:
#                        build/ultima-collection-imported.tcrt (PICK=<image>
#                        chooses when a game has saves on more than one)
#   make disks           find what the build needs in disks/ (any names, .d64,
#                        .g64, zips) and report what is missing
#   make ef              Ultima VI alone on a 1 MiB EasyFlash: build/ultima6-ef.crt
#   make editor          the save editor, one HTML page: build/ultima-save-editor.html
#   make test            the host tests (py65), then the editor's (node)
#   make maps, dialogue  every game's maps as PNGs, its dialogue as text
#   make fixtures        the RAM images some tests need, captured in VICE
#
# Needs: acme, ca65/ld65 (cc65), a C compiler, python3 with py65 (a venv in
# .venv is used when it is there: python3 -m venv .venv && .venv/bin/pip
# install py65); for the editor tsc, bun and node; VICE for `make play`.

VERSION = 1.0
export VERSION

ACME    ?= acme
VENV_PY := $(wildcard .venv/bin/python)
PYTHON  ?= $(if $(VENV_PY),$(VENV_PY),python3)
BUILD    = build
ZX02     = $(BUILD)/tools/zx02
DISKS    = $(BUILD)/disks
CART     = $(BUILD)/ultima-collection.tcrt
PY       = $(PYTHON) -m

PY_SRC  := $(shell find ultima -name '*.py')
ASM_SRC := $(wildcard asm/*.s asm/*.inc ultima/games/*/*.s ultima/games/*/*.inc)
KIT_SRC := $(shell find external/u4remastered/src external/u4remastered/patches -type f 2>/dev/null)
# the editor's game data, generated from your disks (editor/gen_data.py)
EDITOR_GEN := editor/src/games/u6names.ts editor/src/games/u6original.ts

.PHONY: default all cart import disks ef editor editor-test editor-check test maps dialogue play play128 play-ef \
        run-u1test run-u3test run-menu fixtures clean

default: cart ef

all: cart ef editor maps dialogue

# ---- tools ------------------------------------------------------------------
# zx02 (external/zx02), compiled directly: its own Makefile needs GNU make 4
$(ZX02): $(wildcard external/zx02/src/*.c external/zx02/src/*.h)
	@mkdir -p $(@D)
	$(CC) -O3 -DNDEBUG -o $@ external/zx02/src/compress.c external/zx02/src/optimize.c \
	      external/zx02/src/memory.c external/zx02/src/zx02.c

# ---- the disks ----------------------------------------------------------------
# Every image in disks/ is read; what the build needs is found by its hashes
# (ultima/disks/manifest.json) and put together as one stand-in per disk in
# build/disks.  Run again after adding images.
disks:
	$(PY) ultima.disks.scan --write $(DISKS) disks

$(DISKS)/.complete:
	$(PY) ultima.disks.scan --write $(DISKS) disks

# ---- the cart -----------------------------------------------------------------
cart: $(CART)

$(CART): $(ZX02) $(DISKS)/.complete $(PY_SRC) $(ASM_SRC) $(KIT_SRC)
	$(PY) ultima.build $@

# the saved games on your disks, put in by the launcher's own import code
import: $(CART)
	$(PY) ultima.disks.importsave $(CART) disks -o $(BUILD)/ultima-collection-imported.tcrt \
	    $(if $(PICK),--pick "$(PICK)")

# single games, as the tests use them
$(BUILD)/ultima%.tcrt: $(ZX02) $(DISKS)/.complete $(PY_SRC) $(ASM_SRC)
	$(PY) ultima.games.u$*.build $@

# ---- Ultima VI on EasyFlash ------------------------------------------------------
ef: $(BUILD)/ultima6-ef.crt

$(BUILD)/ultima6-ef.crt: $(ZX02) $(DISKS)/.complete $(PY_SRC) $(ASM_SRC) $(wildcard ultima/ef/*.s ultima/ef/*.inc)
	$(PY) ultima.ef.build $@

# ---- VICE -----------------------------------------------------------------------
play: $(CART)
	x64sc -tapeport1device 6 -tcrt $(CART) -tapecartupdatetcrt -keybuf 'load\n'

# Ultima V on a C128: the launcher the page writes to disk, on a disk here
$(BUILD)/u5c128.d64: $(CART)
	rm -f $@
	c1541 -format "ultima v 128,01" d64 $@ -write $(BUILD)/launch128.prg "ultima v 128" >/dev/null

play128: $(BUILD)/u5c128.d64
	x128 -tapeport1device 6 -tcrt $(CART) -tapecartupdatetcrt \
	     -8 $(BUILD)/u5c128.d64 -keybuf 'run"ultima v 128"\n'

play-ef: ef
	x64sc -cartcrt $(BUILD)/ultima6-ef.crt -easyflashcrtwrite

# ---- checks in VICE (tools/vice; VICE 3.11 or later for the key matrix) ----------
# a save round trip from a standalone launcher, every writable entry
$(BUILD)/u1test.prg: asm/boot_u1.s $(BUILD)/ultima1.tcrt
	$(ACME) -f cbm -I asm -I $(BUILD) -DU1_SELFTEST=1 -o $@ -l $(BUILD)/u1test.sym asm/boot_u1.s
$(BUILD)/u3test.prg: asm/boot_u3.s $(BUILD)/ultima3.tcrt
	$(ACME) -f cbm -I asm -I $(BUILD) -DU3_SELFTEST=1 -o $@ -l $(BUILD)/u3test.sym asm/boot_u3.s

run-u1test: $(BUILD)/u1test.prg
	cp $(BUILD)/ultima1.tcrt $(BUILD)/u1test.tcrt
	$(PY) tools.vice.run_vice $(BUILD)/u1test.prg $(BUILD)/u1test.tcrt \
	    --symbols $(BUILD)/u1test.sym --park st_done --update-tcrt
run-u3test: $(BUILD)/u3test.prg
	cp $(BUILD)/ultima3.tcrt $(BUILD)/u3test.tcrt
	$(PY) tools.vice.run_vice $(BUILD)/u3test.prg $(BUILD)/u3test.tcrt \
	    --symbols $(BUILD)/u3test.sym --park st_done --update-tcrt

# the menu comes up, and each game starts from it
run-menu: $(CART)
	$(PY) tools.vice.menu_check
	$(PY) tools.vice.menu_check 0 0x081c
	$(PY) tools.vice.menu_check 1 0x6800
	$(PY) tools.vice.menu_check 2 0xc093
	$(PY) tools.vice.menu_check 3 0x1000
	$(PY) tools.vice.menu_check 4 0x6000
	$(PY) tools.vice.menu_check 5 0x8000

# ---- tests --------------------------------------------------------------------
# The RAM images some host tests run on (tests/data), captured in VICE from
# the cart; those tests skip without them.
fixtures: $(CART)
	$(PY) tools.vice.fixtures

# (the editor's tests need node 22.18 or later: it runs their TypeScript as it is)
test: $(CART) $(BUILD)/ultima1.tcrt $(BUILD)/ultima2.tcrt $(BUILD)/ultima3.tcrt \
      $(BUILD)/ultima4.tcrt $(BUILD)/ultima5.tcrt $(EDITOR_GEN)
	$(PYTHON) -m unittest discover -s tests -t .
	@if node -e 'process.exit(process.features.typescript ? 0 : 1)' 2>/dev/null; then \
	   $(MAKE) --no-print-directory editor-test; \
	 else echo "no node 22.18 or later: the editor's tests skipped"; fi

# ---- the save editor (editor/: a web page, one HTML file) ---------------------
EDITOR_SRC := $(filter-out $(EDITOR_GEN),$(wildcard editor/*.ts editor/src/*.ts editor/src/*/*.ts editor/src/ui/*.css))
# the game data the editor needs, from your disks (not in the repository)
editor/src/games/u6names.ts: $(DISKS)/.complete editor/gen_data.py
	$(PYTHON) editor/gen_data.py
editor/src/games/u6original.ts: editor/src/games/u6names.ts

editor: $(BUILD)/ultima-save-editor.html
$(BUILD)/ultima-save-editor.html: $(EDITOR_SRC) $(EDITOR_GEN)
	cd editor && tsc -p .
	bun editor/build.ts $@

# C64UltimaEditor's sample disks, when its submodule is checked out
C64UE_DATA := $(wildcard external/c64ultimaeditor/C64UltimaEditor/UltimaData.UnitTest/Data/*)
$(BUILD)/editor-fixtures/u1.seq: $(CART) editor/make_fixtures.py $(C64UE_DATA)
	$(PYTHON) editor/make_fixtures.py

editor-test: $(BUILD)/editor-fixtures/u1.seq $(EDITOR_GEN)
	cd editor && tsc -p .
	node --test editor/tests/*.test.ts

editor-check: editor $(BUILD)/editor-fixtures/u1.seq
	node editor/browser_check.ts

# ---- maps and dialogue ------------------------------------------------------------
maps: $(CART)
	$(PY) ultima.maps.u4maps
	$(PY) ultima.maps.u4maps --remastered --out $(BUILD)/maps/u4-remastered
	$(PY) ultima.maps.u3maps
	$(PY) ultima.maps.u2maps
	$(PY) ultima.maps.u5maps
	$(PY) ultima.maps.u1maps
	$(PY) ultima.maps.u6maps

dialogue: $(CART)
	$(PY) ultima.dialogue.u1talk
	$(PY) ultima.dialogue.u2talk
	$(PY) ultima.dialogue.u3talk
	$(PY) ultima.dialogue.u4talk
	$(PY) ultima.dialogue.u4talk --cart
	$(PY) ultima.dialogue.u5talk
	$(PY) ultima.dialogue.u6_dialogue $(BUILD)/dialogue/u6

clean:
	rm -rf $(BUILD)
