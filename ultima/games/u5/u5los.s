; Ultima V, main.subs $4D5D: the view's line of sight, with the neighbour
; test made cheap.
;
; The original floods the 11 x 11 view from the party's square ($3C): each
; cell taken off the stack looks at its eight neighbours (offsets $4E39 in
; the order -12, -1, +10, +11, +12, +1, -10, -11 -- X from 7 down to 0) and
; marks the ones not seen yet: the tile ($4880) if lit -- the light radius
; $0E covers the distance ($4E49), or the square is lit ($4980) -- else $FF,
; with the special cases below; a cell that does not block sight ($5106,
; N clear) is pushed.  Whether a neighbour is in the grid it found by
; adding the offset, refusing 121 and up, and comparing row numbers from a
; table it rebuilt at $7F00 every call: ~33 cycles before even looking at
; the neighbour, ~720 times a step.
;
; Here $7F00 holds, per cell, which of the eight neighbours are in the grid
; (bit i for X = 7 - i: the edges' masks), and a test is a shift and the
; offset (~13 cycles for an edge, ~32 for a neighbour already marked).  The
; cells are visited, marked and pushed exactly as before -- the same order,
; the same stack (the party's square now goes through it too: pushed, then
; taken off at once) -- so the result is the original's in every case: the
; first visit decides a cell's mark.  The original's private tables at
; $4E38-$4E48 are replaced (nothing else names them); the distances at
; $4E49 stay where they are.
;
; Left differently: $7F00-$7F78 (the masks instead of row numbers; the next
; reader of that page, main.twn $997A and main.dng $9450, fills it from a
; record read first, update.himem $1DE4 writes $7F00-$7F0C first), $86 (the
; direction counter's save here, the current row there) and $B5 (the mask
; here, the counter there).  Both are the line of sight's: the only other
; uses in main.subs write them first (checked by the tests, which compare
; memory after the whole view update).

        * = $4D5D

grid    = $4800                 ; what is shown: tile, $FF dark, 0 not reached
tiles   = $4880
lit     = $4980
mask    = $7F00
dist    = $4E49
opaque  = $5106                 ; A = tile, Y = cell: N set if it blocks sight
cur     = $B6
count   = $B4
bits    = $B5
dsave   = $86

los     bit $0A
        bmi $4D51               ; the original's: the window copied from $4400
        ldx #$78
        lda #$00
        ldy $0E
        bpl clear
-       lda tiles,x             ; no light limit: everything is seen
        sta grid,x
        dex
        bpl -
        rts
clear   sta grid,x
        dex
        bpl clear

        ldy #$78                ; the masks: a column's from colm, the top
        ldx #10                 ; and bottom rows lose their up/down bits
-       lda colm,x
        cpy #11
        bcs +
        and #%00111110          ; row 0: not -12, -10, -11
+       cpy #110
        bcc +
        and #%11100011          ; row 10: not +10, +11, +12
+       sta mask,y
        dex
        bpl +
        ldx #10
+       dey
        bpl -

        lda grid + $3C + $80    ; the party's square: seen, and the first cell
        sta grid + $3C          ; (grid + $BC is tiles + $3C)
        lda #$3C
        pha
        lda #1
        sta count

pop     pla
        sta cur
        dec count
        tay
        lda mask,y
        sta bits
        lda lit,y
        sta litcur
        ldx #7
test    lsr bits
        bcc next
        lda cur
        adc offm1,x             ; C is set: the offset less one
        tay
        lda grid,y
        beq new
        cmp #$FF
        bne next
        stx dsave               ; dark: shown after all if seen from a lit
        lda litcur              ; square and it blocks sight
        beq nextx
        lda tiles,y
        jsr opaque
        bpl nextx
show    lda tiles,y
        sta grid,y
        jmp nextx

new     stx dsave
        lda $0E
        cmp #$01
        beq dark
        cmp dist,y
        bcs seen
        lda lit,y
        bne seen
        lda litcur
        beq dark
        lda tiles,y
        jsr opaque
        bmi show
dark    lda #$FF
        sta grid,y
        lda tiles,y
        jmp push
seen    lda tiles,y
        sta grid,y
push    jsr opaque
        bmi nextx
        tya
        pha
        inc count
nextx   ldx dsave
next    dex
        bpl test
        lda count
        bne pop                 ; (exactly the furthest a branch reaches)

done    ldx #$78
        lda #$FF
-       ldy grid,x
        bne +
        sta grid,x
+       dex
        bpl -
        rts

offm1   !byte $F5 - 1, $F6 - 1, $01 - 1, $0C - 1, $0B - 1, $0A - 1, $FF - 1, $F4 - 1
colm    !byte %11111000         ; column 0: not -12, -1, +10
        !fill 9, $FF
        !byte %10001111         ; column 10: not +12, +1, -10
litcur  !byte 0

los_end
        !if los_end > dist { !error "the line of sight reaches $4E49" }
