;;; u5powers.s -- the launcher's X for Ultima V: F7 teleports, in the world
;;; the party is in, and B(oard) where there is nothing to board brings a
;;; horse, a carpet, a ship or a skiff.
;;;
;;; Appended to MAIN.OUT, the overworld's mode root (2A: $8000-$A479, 2B:
;;; $8000-$A46F), so it loads with it, wherever it is loaded from; build.py
;;; assembles it once for each disk.  Up to $A6FF nothing the overworld runs
;;; reaches (the overlays start at $A700; MAIN.COMBAT covers the range, and
;;; MAIN.OUT is loaded again after a fight).  On a C128 the mode-root swap
;;; moves $8000-$ACFF whole, this with it.
;;;
;;; The hooks are the option's patches (build.py OPTION_PATCHES, bit
;;; POWERS), two of the command loop's `JSR $4C00 / "What?"`, each becoming
;;; a JSR to one of the two JMPs at the start: the answer to a key it does
;;; not know ($8275, 2B $826B) to `tele`, and Board's when there is no
;;; vehicle under the party ($86E5, 2B $86DB) to `board`.  Anything they do
;;; not take goes on to $4C00, which prints the inline "What?" after the JSR
;;; as before and returns past it, to the JMP that ends the turn.
;;;
;;; tele: F7 ($88 in the raw key; DEL gives the same code) asks for X and Y,
;;; 0-255 each, up to three digits ended by RETURN; anything else, or a
;;; number above 255, gives up and no turn passes.  The position is
;;; $2D/$2E; JSR $8003 (MAIN.OUT's own entry, as Blink in C does) builds the
;;; rest from it: the 32 x 32 window and its four chunks, the party's place in
;;; it, the lights, the moons, the status line.  The object list's slot 0,
;;; PRTY.DATA (zero page $02-$31) and the monsters' turn follow from it.
;;; Heading and sailing are cleared, as the overworld's entry ($8011) and a
;;; blocked ship ($84E9) clear them.  The square landed on is not looked at.
;;;
;;; board: Board ($86B2) found no object under the party (A = 0 from $880E)
;;; and the party is on foot ($0C $1C/$1D): H)orse, C)arpet, S)hip or
;;; sK)iff, and the party is in it, as Board leaves it after taking one:
;;; the party's shape $0C (a horse $12, as Board makes of a horse object; a
;;; carpet $15; a ship $25 and a skiff $29, the shipwright's as the
;;; overworld's entry delivers them at $8063), a ship's hull ($4AC0, slot 0's)
;;; 99 and its skiffs ($17) 2, as TALK.SH sells it ($82: a ship, two skiffs)
;;; and $8071 delivers it; the ship's music for a ship or a skiff (song 3,
;;; as Board), the objects redrawn ($80), the turn ended.  X(it) leaves it
;;; behind as an object, as it does any other.  Any other key: no turn.  The
;;; square is not looked at: X(it) works on land and water alike.
;;;
;;; Defined by build.py: TELE (the address), KEY (the raw key), TURN (the
;;; end of a turn), LOOP (the command loop, no turn), HEADING, SAILING.

PRINT_INLINE = $4c00            ; the string after the JSR, bit 7 set, 0 ends it
PRINT_CHAR   = $4c03            ; A, bit 7 set; $8D a new line
PRINT_DIGIT  = $4c09            ; A's low nibble
NEWLINE      = $4c06
GETKEY       = $4c15            ; wait; digits $B0-$B9, letters $C1-$DA, RETURN $0D
MUSIC        = $6c46            ; play song A (Board's, for a ship)
ENTRY        = $8003            ; the map and view from $2D/$2E
POS_X        = $2d
POS_Y        = $2e
SHAPE        = $0c              ; the party's tile: on foot $1C/$1D
SKIFFS       = $17
HULL         = $4ac0            ; slot 0's: the party's ship
REDRAW       = $80              ; the objects drawn again at the turn's end
KEY_F7       = $88

        * = TELE
        jmp tele                ; TELE + 0: the unknown key's hook
        jmp board               ; TELE + 3: Board's

tele:   lda KEY
        cmp #KEY_F7
        beq +
        jmp PRINT_INLINE        ; "What?", as before
+       pla                     ; (the string's address)
        pla
        jsr PRINT_INLINE
        !xor $80 { !text "Teleport" }
        !byte $8d
        !xor $80 { !text "X-" }
        !byte 0
        jsr number
        bcs giveup
        sta newx
        jsr PRINT_INLINE
        !xor $80 { !text " Y-" }
        !byte 0
        jsr number
        bcs giveup
        sta POS_Y
        lda newx
        sta POS_X
        jsr NEWLINE
        lda #$00
        sta HEADING
        sta SAILING
        jsr ENTRY
        jmp TURN

giveup: jsr NEWLINE
        jmp LOOP

;;; 0-255: up to three digits, RETURN after one or two.  A = the number,
;;; carry clear; carry set for anything else.
number: lda #$00
        sta value
        sta digits
nm_key: jsr GETKEY
        cmp #$0d
        bne +
        lda digits
        beq nm_no               ; RETURN before a digit
        bne nm_end
+       eor #$b0
        cmp #10
        bcs nm_no
        sta digit
        lda value               ; value * 10 + digit, at most 255
        asl
        bcs nm_no
        sta times2
        asl
        bcs nm_no
        asl
        bcs nm_no
        adc times2
        bcs nm_no
        adc digit
        bcs nm_no
        sta value
        lda digit
        jsr PRINT_DIGIT
        inc digits
        lda digits
        cmp #3
        bne nm_key
nm_end: lda value
        clc
        rts
nm_no:  sec
        rts

;;; A = the object Board found under the party, 0 for none
board:  cmp #$00
        bne +
        lda SHAPE
        and #$fe
        cmp #$1c
        beq bd_ask
+       jmp PRINT_INLINE        ; "What?", as before
bd_ask: pla                     ; (the string's address)
        pla
        jsr PRINT_INLINE
        !byte $8d
        !xor $80 { !text "H)orse C)arpet" }
        !byte $8d
        !xor $80 { !text "S)hip sK)iff?" }
        !byte $8d, 0            ; (the name on a line of its own: 16 columns)
        jsr GETKEY
        ldx #3
-       cmp bd_keys,x
        beq bd_take
        dex
        bpl -
        jmp giveup
bd_take:
        stx choice
        lda bd_shapes,x
        sta SHAPE
        ldy bd_names,x
-       lda bd_text,y           ; the vehicle's name, as Board prints it
        sty at
        jsr PRINT_CHAR
        ldy at
        lda bd_text,y
        iny
        cmp #$8d
        bne -
        ldx choice
        cpx #2
        bcc bd_end              ; a horse or a carpet
        bne +
        lda #$99                ; a ship: hull 99 (BCD), two skiffs
        sta HULL
        lda #2
        sta SKIFFS
+       lda #3                  ; a ship or a skiff: the ship's music
        jsr MUSIC
bd_end: inc REDRAW
        jmp TURN

bd_keys:   !byte 'H' | $80, 'C' | $80, 'S' | $80, 'K' | $80
bd_shapes: !byte $12, $15, $25, $29
bd_names:  !byte bd_horse - bd_text, bd_carpet - bd_text, bd_ship - bd_text, bd_skiff - bd_text
bd_text:
bd_horse:  !xor $80 { !text "Horse" }
           !byte $8d
bd_carpet: !xor $80 { !text "Carpet" }
           !byte $8d
bd_ship:   !xor $80 { !text "Ship" }
           !byte $8d
bd_skiff:  !xor $80 { !text "Skiff" }
           !byte $8d

newx:   !byte 0
value:  !byte 0
digits: !byte 0
digit:  !byte 0
times2: !byte 0
choice: !byte 0
at:     !byte 0
powers_end:
!if powers_end > $a700 {
        !error "u5powers.s runs into the overlays at $A700: ", powers_end
}
