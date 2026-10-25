; Ultima V, main.subs $572B: the tile animation, as straight loops.
;
; The original cycles the frames of seven animated tiles in the tile set
; under the I/O ($C000-$DFFF, 32 bytes a tile, frames in consecutive tiles):
; four frames at $DA80, $DB00 and $DD80 ($576D: tile k <- tile k+1, the last
; <- the first) and two at $DF40, $DF80, $D000 and $D040 ($57BC: a swap).
; Every byte moved went through `JSR $57AC` / `JSR $57B4` (Y +/- $20), about
; 11k cycles for one four-frame set, ~36k a step.  The addresses are all
; constants, so here every set is spelt out with absolute,Y operands, and
; the sets done on the same turn share one loop over the 32 columns.  The
; sets are disjoint and each column of a set is independent, so the order
; does not matter.  Which sets move when is the original's: $DA80 and $DB00
; every call, $DF40 and $DF80 when the counter $572A (incremented first) is
; a multiple of 4, $D000, $D040 and $DD80 when it is even.
;
; Left as the original left them: $FC/$FD, the last set's address, which
; nothing reads before writing (checked by the tests: the view update's
; memory after both versions).  A, X, Y and the flags differ: $57DE, which
; comes next, starts with LDA and keeps X and Y only on paths that load
; them first, and the view update ends LDX #0 / LDY #0.

        * = $572B

count   = $572A                 ; the original's turn counter

!macro rot4 .b {           ; tile k <- tile k+1, tile 3 <- tile 0, column Y
        lda .b,y
        pha
        lda .b + $20,y
        sta .b,y
        lda .b + $40,y
        sta .b + $20,y
        lda .b + $60,y
        sta .b + $40,y
        pla
        sta .b + $60,y
}

!macro swap .b {           ; tile 0 <-> tile 1, column Y
        lda .b,y
        pha
        lda .b + $20,y
        sta .b,y
        pla
        sta .b + $20,y
}

anim    ldy #$1F
-       +rot4 $DA80
        +rot4 $DB00
        dey
        bpl -
        inc count
        lda count
        lsr                     ; odd: nothing more
        bcs odd
        lsr                     ; a multiple of 4: the two swaps at $DF40, $DF80
        bcs even
        ldy #$1F
-       +swap $DF40
        +swap $DF80
        dey
        bpl -
even    ldy #$1F
-       +swap $D000
        +swap $D040
        +rot4 $DD80
        dey
        bpl -
        lda #$DD                ; $FC/$FD as the original leaves them: the last set
        ldx #$80
        bne +
odd     lda #$DB
        ldx #$00
+       sta $FD
        stx $FC
        rts

anim_end
        !if anim_end > $57DE { !error "the animation reaches $57DE" }
