;;; u4scrollc.s -- the end of u4scroll.s: the colour of the text window's
;;; last row ($0400 + 23 * 40 + 24 = $07B0, 16 bytes) set to a space's, $10.
;;; In SUBS' dead swap prompt, right after u4key.s (which ends at $19A2) and
;;; before $19B7, which is left alone.

        * = $19a3
ts_colour:
        ldy #$0f
        lda #$10
-       sta $07b0,y
        dey
        bpl -
        rts
