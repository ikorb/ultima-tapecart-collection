;;; u2powers.s -- F1 tells where, F7 teleports, B brings a transport: the
;;; launcher's X for U2.
;;;
;;; Ultima III Gold's and Ultima IV Remastered's (U3's F7 and B, U4's T and
;;; B), for Ultima II.  ULTIMA's command loop
;;; (the surface's and the towns', $8E14 = 0-3) sends a key below the letters
;;; that is not a direction, space or : / ; @ to "ILLEGAL COMMAND!" ($5233 JMP
;;; $6702); Board, on foot where there is nothing to board, says "WHAT?"
;;; ($72CD JSR $4006, the inline print).  Both are hooked at build time
;;; (build.py POWER_HOOKS), and with pw_on ($80, the launch's poke) on the
;;; surface ($8E14 = 0: Earth's ages and the planets):
;;;   F1: "POSITION X-30 Y-31", where the party is ($02, $03), as F7 takes
;;;       it.  No turn passes: on to the prompt ($50E7, where the turn's end
;;;       goes after the monsters), not to the command's end.
;;;   F7: X and Y, two digits each, 00-63 (the map is 64 x 64, $1000), and
;;;       the party is there ($02, $03); anything else, "WHAT?".
;;;   B:  "(H)ORSE,(F)RIGATE,(P)LANE-" on a line of its own (26 of the text
;;;       area's 29 columns; Board's "BOARD" is on the CMD: line), H, F or P:
;;;       the transport is $13 (Board takes
;;;       the tile off the map and keeps it there, $22/$24/$26; Exit puts it
;;;       back on grass, a frigate on water too).  No rocket: a launch is the
;;;       game's way between Earth and the planets.
;;; ($14-$18, the tile under the party and its neighbours that Board, Exit
;;; and the moves test, come from the view's drawing, $4A2C, after every
;;; command -- so a teleport leaves none of them stale.)
;;; Without the option, or off the surface, the original's way.  Keys: $38,
;;; bit 7 set while one waits, $4075 takes it; $4057 prints A (A and Y kept);
;;; $4006 the inline string after the JSR.
;;;
;;; Assembled on its own (build.py) into SUBS' disk block code, $4E6A-$4F78,
;;; dead since its two vectors ($40AB, $40AE) go to the driver.  pw_on, the
;;; launch poke's target, stays in the driver; build.py passes its address
;;; (acme -D).

        * = $4e6a

;;; $5233's JMP $6702, A = the key
pw_key: bit pw_on
        bpl +
        ldx $8e14
        bne +
        cmp #$88                ; F7
        beq pw_teleport
        cmp #$85                ; F1
        beq pw_where
+       jmp $6702               ; ILLEGAL COMMAND!

pw_where:
        jsr $4006
        !byte $d0, $cf, $d3, $c9, $d4, $c9, $cf, $ce, $a0, $d8, $ad, 0    ; "POSITION X-"
        lda $02
        jsr pw_print
        jsr $4006
        !byte $a0, $d9, $ad, 0                                          ; " Y-"
        lda $03
        jsr pw_print
        lda #$8d                ; the line's end, as $52C0's
        jsr $4057
        jmp $50e7               ; the prompt: no turn

;;; A (0-99) as two digits
pw_print:
        ldy #$af                ; "0" - 1
-       iny
        sec
        sbc #10
        bcs -
        adc #$ba                ; the units: + 10 + "0" (C clear)
        pha
        tya
        jsr $4057
        pla
        jmp $4057

pw_teleport:
        jsr $4006
        !byte $d4, $c5, $cc, $c5, $d0, $cf, $d2, $d4, $a0, $d8, $ad, 0    ; "TELEPORT X-"
        jsr pw_number
        bcs pw_no
        pha                     ; X, until Y is good too
        jsr $4006
        !byte $a0, $d9, $ad, 0                                          ; " Y-"
        jsr pw_number
        bcs pw_nox
        sta $03
        pla
        sta $02
        jmp $52c0               ; the command's end
pw_nox: pla
pw_no:  jsr $4006
        !byte $a0, $d7, $c8, $c1, $d4, $bf, $87, 0                      ; " WHAT?"
        jmp $52c0

;;; two digits, at most 63: A and C clear; anything else C set
pw_number:
        jsr pw_digit
        bcs ++
        asl                     ; x 10
        sta pw_t
        asl
        asl
        adc pw_t
        sta pw_t
        jsr pw_digit
        bcs ++
        adc pw_t                ; (C clear)
        cmp #64
++      rts

;;; a key: a digit, printed, as 0-9 and C clear; else C set
pw_digit:
-       lda $38
        bpl -
        jsr $4075               ; (A and P kept)
        eor #$b0                ; "0"-"9": 0-9
        cmp #10
        bcs +
        ora #$b0
        jsr $4057
        and #$0f
        clc
+       rts

;;; $72CD's JSR $4006 " WHAT?": called as that JSR, so the print (a tail
;;; call) finds its inline string after the JSR as before
pw_board:
        bit pw_on
        bpl +
        lda $8e14
        bne +
        pla                     ; not coming back to the print
        pla
        jsr $4006
        !byte $8d, $a8, $c8, $a9, $cf, $d2, $d3, $c5, $ac              ; CR "(H)ORSE,"
        !byte $a8, $c6, $a9, $d2, $c9, $c7, $c1, $d4, $c5, $ac         ; "(F)RIGATE,"
        !byte $a8, $d0, $a9, $cc, $c1, $ce, $c5, $ad, 0                ; "(P)LANE-"
-       lda $38
        bpl -
        jsr $4075
        ldx #2
-       cmp pw_keys,x
        beq ++
        dex
        bpl -
        jmp $52c0               ; none of them: nothing
++      jsr $4057
        lda pw_tiles,x
        sta $13
        jmp $52c0
+       jmp $4006

pw_keys:  !byte $c8, $c6, $d0   ; H F P
pw_tiles: !byte $22, $24, $26   ; horse, frigate, plane
pw_t:     !byte 0
pw_end:
!if pw_end > $4f79 {
        !error "u2powers.s runs into SUBS' RNG at $4F79 by ", pw_end - $4f79, " bytes"
}
