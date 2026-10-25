;;; u3view.s -- UPDT's line of sight in one pass.
;;;
;;; UPDT ($CA09) puts the 11 x 11 squares around the party into $9900 (row
;;; by row, the party at $3C), then hides what the party cannot see
;;; ($CA99-$CB00): for each square from the last (index 120, $73) to the
;;; first it walks toward the party, a step at a time -- x and y each one
;;; nearer until they are the party's ($CBE8: +1, 0, -1 by x; $CBF3: +11,
;;; 0, -11 by y) -- and if a square on the way, not the party's, holds a
;;; blocker ($06, $08, $46, $48) the square becomes $48.  34-44k cycles.
;;;
;;; The walk from a square goes on exactly as the walk from its first step
;;; does.  So a square is hidden if its first step is a blocker or hidden
;;; itself -- and a hidden square holds $48, a blocker -- which is one test
;;; a square, when the squares are taken nearest the party first: the
;;; party's row outward from it, then the rows above it upward and the rows
;;; below it downward.  (The original's order makes no difference: a square
;;; marked $48 before another's walk reaches it is one whose own walk ends
;;; on a blocker further along the same way.)
;;;
;;; build.py points $CA99 here.  The first square, index 0, is left to the
;;; original code ($CAA3, with $73, $77 and $78 = 0), which then ends the
;;; pass as it always did: $73, $75-$78 and $7B as the original leaves
;;; them, the registers too.  $75, $76 and $7B are scratch here.

UPDT_DX = $cbe8                 ; by x: +1, 0, -1
UPDT_DY = $cbf3                 ; by y: +11, 0, -11
VIEW = $9900
CENTRE = 5 * 11 + 5

vw_los:
        lda #5                  ; the party's row, to the right
        sta $76
        lda #6
        sta $75
        ldx #CENTRE + 1
-       jsr vw_one
        inx
        inc $75
        lda $75
        cmp #11
        bne -
        lda #4                  ; ... and to the left
        sta $75
        ldx #CENTRE - 1
-       jsr vw_one
        dex
        dec $75
        bpl -
        dec $76                 ; the rows above, up to index 1
--      lda #10
        sta $75
-       jsr vw_one
        dex
        beq +
        dec $75
        bpl -
        dec $76
        bpl --                  ; (always: X reaches 0 in row 0)
+       lda #6                  ; the rows below, down
        sta $76
        ldx #CENTRE + 6
--      lda #0
        sta $75
-       jsr vw_one
        inx
        inc $75
        lda $75
        cmp #11
        bne -
        inc $76
        lda $76
        cmp #11
        bne --
        lda #0                  ; square 0 by the original, which ends the pass
        sta $73
        sta $77
        sta $78
        jmp $caa3

;;; square X at ($75, $76): $48 if its first step toward the party is a
;;; blocker or hidden; X kept
vw_one:
        txa
        ldy $75
        clc
        adc UPDT_DX,y
        ldy $76
        clc
        adc UPDT_DY,y
        cmp #CENTRE
        beq +                   ; next to the party: seen
        tay
        lda VIEW,y
        cmp #$06
        beq ++
        cmp #$08
        beq ++
        cmp #$46
        beq ++
        cmp #$48
        bne +
++      lda #$48
        sta VIEW,x
+       rts
