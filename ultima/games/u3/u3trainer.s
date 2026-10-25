;;; u3trainer.s -- Ultima III Gold's "ingame keys", behind a launcher option.
;;;
;;; Gold's trainer code is in our ULT3 already (Gold's image, its tail
;;; $922F-$93FF: 3/gold/GOLD-ANALYSIS.md 5.5); only its hooks were Gold BOOT's,
;;; applied when the trainer was answered Y.  Here the hooks are always in
;;; (ultima/games/u3/build.py TRAINER_HOOKS) and come to these stubs, which take
;;; Gold's path when the launcher's option has set tr_on, else the original's:
;;;   B with nothing to board: S(hip) or H(orse) ($934C), else "WHAT?" ($520F);
;;;   F7 (key code $88) on the surface: the teleport, asking X and Y ($9375);
;;;   X in combat: straight to "VICTORY!" ($93F1 -> $834E);
;;;   O(ther command), AMBROSIA: the whirlpool's sequence to Ambrosia ($756B).
;;; (Gold's notes call it "Yell"; the hook is in Other's word check, "CMD:",
;;; where EVOCARE is -- checked in VICE.)  Other tells words apart by their
;;; last letter and length alone (A, X = 8 - length), so "AMBROSIA" is any
;;; 8-letter word ending in A, as in Gold.  Gold's hook took the 18 bytes of
;;; "NO EFFECT!" and printed "FAILED!" instead; this one is a JSR over the
;;; print's own JSR, so a word that does nothing still gets NO EFFECT!.  In
;;; the driver's decoder segment.

tr_on:  !byte 0                 ; the launcher's option: $80 = on (a launch poke)

;;; $52AF's JMP: nothing to board
tr_board:
        bit tr_on
        bmi +
        jmp $520f               ; WHAT?
+       jmp $934c               ; Gold's: S / H

;;; $50E5's CMP #$A0 / BNE $50F5 (space passes, else on through the dispatcher)
tr_key: bit tr_on
        bmi +
        cmp #$a0
        beq ++
        jmp $50f5
++      jmp $50e9
+       jmp $9375               ; Gold's: F7 teleports, then the same test

;;; $801E's JMP $80FE in combat's command dispatcher
tr_fight:
        bit tr_on
        bmi +
        jmp $80fe
+       jmp $93f1               ; Gold's: X wins

;;; Other's $61DA, JSR $46C3 "NO EFFECT!": called as that JSR, so the print (a
;;; tail call) finds its inline string after the JSR as before
tr_other:
        bit tr_on
        bpl +
        cmp #$c1                ; ...A
        bne +
        cpx #$00                ; 8 letters
        bne +
        pla                     ; not coming back to the print
        pla
        jsr $756b               ; the whirlpool's sequence: to Ambrosia
        jmp $6d38               ; the command's end
+       jmp $46c3

;;; The map of Sosaria kept whole with the keys on.  ULT3 assumes a frigate
;;; stands on water (or the whirlpool) and a horse on grass: Board puts back
;;; water ($52D0) or grass ($52B2) where the craft was parked, and X-it
;;; ($6951) parks it on any square below $05, water or grass.  The keys put
;;; crafts anywhere: B conjures one on the party's square (Gold's tail goes
;;; through Board's writes, see build.py), the teleport carries one along,
;;; and AMBROSIA is the whirlpool's trip, which clears the party's square on
;;; the way down and brings it back on a frigate there.  These stubs are
;;; always in: in the original's play each one does what the original did.

;;; The whirlpool's trip.  $762B clears the party's square to water, meant
;;; for the whirlpool's tile ($30) under the frigate, and on the way back
;;; $7777 makes the party a frigate there.  Said on land, AMBROSIA turned the
;;; land to water (a castle or town, said on its tile) and left a frigate on
;;; it.  By the whirlpool the tile is always $30, and the square water again.

;;; $762B's JSR $4708 / LDA #$00 / STA ($7E),Y, the party's square in $02/$03
tr_pool:
        jsr $4708               ; its tile, ($7E),Y at it
        cmp #$30                ; the whirlpool's
        bne +
        lda #$00                ; water
        sta ($7e),y
+       rts

;;; $7777's LDA #$16 / STA $60: back on Sosaria, $F7/$F8 the square left from
;;; and the map restored
tr_back:
        jsr $4705               ; the tile at $F7/$F8
        beq +                   ; water: on a frigate, as the original
        lda #$7e                ; else on foot
        !byte $2c               ; (BIT abs: skips the LDA #$16)
+       lda #$16
        sta $60
        rts

;;; $6951's LDA $0E / ASL / STA ($7E),Y: X-it parks the craft, A the square's
;;; tile (water or grass, $6947 refused the rest), ($7E),Y at it.  A frigate
;;; is parked on water and a horse on grass, the squares Board puts back; on
;;; any other the craft stays behind unparked and the square keeps its tile
tr_xit: ldx $0e                 ; the craft: $16 a frigate, $14 a horse
        cpx #$16
        bne +
        eor #$04                ; a frigate's water as a horse's grass
+       cmp #$04
        bne +
        txa
        asl                     ; its tile on the map: $2C, $28
        sta ($7e),y
+       rts
