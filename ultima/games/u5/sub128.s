;;; sub128.s -- Ultima V's subs.128, the C128 overlay cache, run from bank 1.
;;;
;;; On a C128 Ultima V loads subs.128 at $7700, over the fastloader.  On the
;;; cart that is our driver, so the cache's code moves here, to RAM bank 1,
;;; and the eight entries at $7700 reach it through C_FAR (c128.inc).  What
;;; each does is subs.128's, entry for entry (disassembled from disk 1A):
;;;
;;;   $7700  fetch overlay A to $A700: from bank 1 if it is one of the
;;;          eleven cached (C E I M P R S T U V Z), else load it by name
;;;   $7703  play song X ($03CD = $03CC = X, spin until $03CE says so)
;;;   $7706  restart the selected song ($03CD -> $03CC)
;;;   $7709  swap the mode root, $8000-$ACFF, with bank 1 $A000-$CCFF --
;;;          or, once called with anything but X/Y = $12/$34, $8000-$A6FF
;;;          with $A000-$C6FF, then put $A700 back (a page from the VDC, and
;;;          six from bank 1 if $8001 reads $E9 $81) and JMP $8000.  The
;;;          original patches itself for that and nothing patches it back,
;;;          so neither does this: t3mode stays set.
;;;   $770C  load Q and put its first page in the VDC at $3E00, then load
;;;          the eleven and stash each in bank 1 (Journey Onward's preload)
;;;   $770F  exchange $C000-$FCFF with the VDC's $0000-$3CFF; A is a tag
;;;          for which map that is, the old one comes back in A
;;;   $7712  exchange the C128 KERNAL's $0A00-$0A28 with a buffer
;;;   $7715  ours: the music setup xyzzy did with `m` in bank 0 ($720F):
;;;          the launcher put `m` in bank 1 already, so this copies its two
;;;          common-RAM pieces down, installs C_B0 and starts the player
;;;
;;; It runs with the MMU at $7F -- bank 1, all RAM, no I/O: overlay U is
;;; cached at $CD00-$DFFF -- and brings the I/O in only around the VDC.
;;;
;;; Where the original ran in bank 0 and reached bank 1 through the KERNAL's
;;; FETCH/STASH trampolines ($02A2/$02AF), this runs in bank 1 and reaches
;;; bank 0 through the same two -- one trampoline call per byte either way,
;;; so the cache is as fast as it was.  The one bank-0 routine it used,
;;; update.himem's $1D8F (exchange a RAM page with a VDC page), is done here
;;; directly on the VDC, which the net effect of the original's
;;; swap-exchange-swap through $7F00 equals.  Loads go through C_B0 and the
;;; driver's u5_c128_ld.  The final state is the original's: after a copy,
;;; its $6C03 (MMU $0E, $01 $26 -- the motor-safe value -- and CLI).
;;;
;;; Contract with C_FAR: A = the caller's A, X and Y the caller's, C_IDX =
;;; the entry's JSR return address low byte; at the top level of an entry
;;; the caller's MMU value is at $0103,x after TSX.  Return A = the MMU
;;; value to leave with, C_A = the A to hand back.

!source "c128.inc"

FETCH   = $02a2                 ; LDA (FPTR),Y in configuration X; X := old
FPTR    = $02aa
STASH   = $02af                 ; STA (SPTR),Y in configuration X; X := old
SPTR    = $02b9
ZP      = $fe                   ; subs.128's own pointer, (ZP),Y
VDC     = $d600
VDATA   = $d601

;;; from build.py: U5_C128_LD, U5_C128_LETTER (the driver's load stub), and
;;; sub128_data.s -- subs.128's tables, copied from the file
        * = B1_ORG
        stx x_in
        ldx #<C_RTS
        stx C_VEC
        ldx #>C_RTS
        stx C_VEC+1
        ldx C_IDX
        lda jt-2,x              ; low bytes $02, $05, ... $17: one per three
        sta jv
        lda jt-1,x
        sta jv+1
        lda C_A
        ldx x_in
        jmp (jv)

jt:     !word t0
        !byte 0
        !word t1
        !byte 0
        !word t2
        !byte 0
        !word t3
        !byte 0
        !word t4
        !byte 0
        !word t5
        !byte 0
        !word t6
        !byte 0
        !word t7
jv:     !word 0
x_in:   !byte 0

;;; leave with the caller's configuration, A = C_A (entries that copy
;;; nothing: the original's MMU and I flag are untouched)
!macro as_called {
        stx x_in
        tsx
        lda $0103,x
        ldx x_in
        rts
}

;;; leave as the original's last $6C03 did
done_io:
        lda #$26
        sta $01
        cli
        lda #MMU_IO
        rts

;;; ==================================================================
;;; $7700 -- fetch overlay A to $A700
;;; ==================================================================
t0:     pha
        tsx
        lda $0104,x             ; (one deeper for the PHA)
        sta C_CFG               ; a load happens as it was called
        pla
        ldx #$00
-       cmp letters,x
        beq t0_hit
        inx
        ldy letters,x
        bne -
t0_ld:  jsr load_letter         ; not cached: load it, until it loads
        bcs t0_ld
        sta C_A
        +as_called
t0_hit: lda first,x
        sta src
        lda last,x
        sta endp
        lda #$a7
        sta dst
-       jsr b1_to_b0
        cli                     ; (the original's $6C03, every page)
        inc src
        inc dst
        lda src
        cmp endp
        bne -
        sta C_A
        jmp done_io

;;; ==================================================================
;;; $7703 / $7706 -- the music's song request
;;; ==================================================================
t1:     stx $03cd
        stx $03cc
        lda $79                 ; music on?
        bpl t1_out
        ldy #$ff
        tya
-       cpx $03ce               ; until the player has taken it up, or
        beq t1_out              ; about 65536 x 256 polls
        dey
        bne -
        sbc #$01
        bne -
t1_out: sta C_A
        +as_called

t2:     lda $03cd
        sta $03cc
        sta C_A
        +as_called

;;; ==================================================================
;;; $7709 -- swap the mode root with bank 1
;;; ==================================================================
t3:     cpx #$12
        bne +
        cpy #$34
        beq ++
+       lda #$01
        sta t3mode
++      lda #$80
        sta src                 ; bank 0
        lda #$a0
        sta dst                 ; bank 1
        lda #$cd
        ldx t3mode
        beq +
        lda #$c7
+       sta endp
-       jsr xchg
        cli
        inc src
        inc dst
        lda dst
        cmp endp
        bne -
        sta C_A
        lda t3mode
        bne +
        jmp done_io             ; the original's RTS
+       lda #$a7                ; $A700: a page from the VDC's $3E00
        sta dst
        lda #$3e
        sta vpage
        jsr vdc_to_b0
        lda #$00                ; and six from bank 1 if the mode root is
        sta ZP                  ; the one that wants them
        lda #$80
        sta ZP+1
        lda #ZP
        sta FPTR
        ldy #$01
        ldx #MMU_B0
        jsr FETCH
        cmp #$e9
        bne t3_go
        iny
        ldx #MMU_B0
        jsr FETCH
        cmp #$81
        bne t3_go
        lda src                 ; bank 0 $A7.. from bank 1 $C7..
        sta dst
        lda endp
        sta src
-       jsr b1_to_b0
        cli
        inc dst
        inc src
        lda src
        cmp #$cd
        bne -
t3_go:  lda #$00                ; JMP $8000
        sta C_VEC
        lda #$80
        sta C_VEC+1
        jmp done_io

;;; ==================================================================
;;; $770C -- load Q and the eleven, stash them
;;; ==================================================================
t4:     tsx
        lda $0103,x
        sta C_CFG               ; Q loads as it was called, the rest after
        lda #$00                ; a copy's $6C03
        sta t4i
        lda #"Q"                ; (once: the original does not retry)
        jsr load_letter
        lda #MMU_IO
        sta C_CFG
        lda #$a7
        sta src
        lda #$3e
        sta vpage
        jsr vdc_xchg
t4_next:
        ldx t4i
        inc t4i
        lda letters,x
        bne +
        sta C_A
        jmp done_io
+       sta t4l
-       lda t4l
        jsr load_letter
        bcs -
        ldx t4i
        dex
        lda first,x
        sta dst
        lda last,x
        sta endp
        lda #$a7
        sta src
-       jsr b0_to_b1
        cli
        inc src
        inc dst
        lda dst
        cmp endp
        bne -
        beq t4_next

;;; ==================================================================
;;; $770F -- exchange $C000-$FCFF with the VDC's first 61 pages
;;; ==================================================================
t5:     sta t5new
        lda #$c0
        sta src
        lda #$00
        sta vpage
-       jsr vdc_xchg
        cli
        inc src
        inc vpage
        lda vpage
        cmp #$3d
        bne -
        lda tag                 ; the old tag back in A, the new in X
        sta C_A
        ldx t5new
        stx tag
        jmp done_io

;;; ==================================================================
;;; $7712 -- exchange $0A00-$0A28 (bank 0) with the buffer
;;; ==================================================================
t6:     lda #$00
        sta ZP
        lda #$0a
        sta ZP+1
        lda #ZP
        sta FPTR
        sta SPTR
        ldy #$28
-       ldx #MMU_B0
        jsr FETCH
        pha
        lda kbuf,y
        ldx #MMU_B0
        jsr STASH
        pla
        sta kbuf,y
        dey
        bpl -
        sta C_A
        ldx #$ff                ; as the original leaves it
        +as_called

;;; ==================================================================
;;; $7715 -- the music setup (xyzzy's C128 path calls it for `m`)
;;; ==================================================================
t7:     php
        sei
        ldx #$51                ; $7BDB-$7C2B -> $0123-$0173
-       lda $7bda,x
        sta $0122,x
        dex
        bne -
        ldx #$72                ; $7C2C-$7C9D -> $0220-$0291
-       lda $7c2b,x
        sta $021f,x
        dex
        bne -
        ldx #c_b0_end - c_b0 - 1
-       lda c_b0,x
        sta C_B0,x
        dex
        bpl -
        lda #$00                ; as $0269's bank copy leaves its pointer
        sta $50
        lda #$a1
        sta $51
        lda $c8                 ; the music is there: bit 6, which the
        ora #$40                ; games' music gates test (build.py
        sta $c8                 ; MUSIC_GATES; a C64 with an AR sets it too)
        lda #$00                ; no reset hook: the KERNAL's reset jumps
        sta $fff5               ; through $FFF8 here when $FFF5 says "CBM",
                                ; and startup ($82B8) puts its NMI stub there
        plp
        sec                     ; (as $0269's copy loop leaves it)
        jsr $0123               ; start the player: timer, vectors in both
        sta C_A                 ; banks
        +as_called

;;; ==================================================================
;;; helpers
;;; ==================================================================
;;; load the overlay named by the letter in A, in bank 0; C set if it failed
load_letter:
        pha
        lda #<U5_C128_LETTER
        sta ZP
        lda #>U5_C128_LETTER
        sta ZP+1
        lda #ZP
        sta SPTR
        pla
        ldy #$00
        ldx #MMU_B0
        jsr STASH
        jmp C_B0

;;; page src (bank 1) -> page dst (bank 0)
b1_to_b0:
        lda #$00
        sta ZP
        lda dst
        sta ZP+1
        lda #ZP
        sta SPTR
        lda src
        sta b1r+2
        ldy #$00
b1r:    lda $ff00,y
        ldx #MMU_B0
        jsr STASH
        iny
        bne b1r
        rts

;;; page src (bank 0) -> page dst (bank 1)
b0_to_b1:
        lda #$00
        sta ZP
        lda src
        sta ZP+1
        lda #ZP
        sta FPTR
        lda dst
        sta b1w+2
        ldy #$00
-       ldx #MMU_B0
        jsr FETCH
b1w:    sta $ff00,y
        iny
        bne -
        rts

;;; exchange page src (bank 0) with page dst (bank 1)
xchg:   lda #$00
        sta ZP
        lda src
        sta ZP+1
        lda #ZP
        sta FPTR
        sta SPTR
        lda dst
        sta xr+2
        sta xw+2
        ldy #$00
xr:     lda $ff00,y
        pha
        ldx #MMU_B0
        jsr FETCH
xw:     sta $ff00,y
        pla
        ldx #MMU_B0
        jsr STASH
        iny
        bne xr
        rts

;;; exchange page src (bank 0) with VDC page vpage (update.himem's $1D8F)
vdc_xchg:
        lda #MMU_B1IO           ; the VDC's registers in view (nothing of
        sta $ff00               ; bank 1's is touched here)
        lda #$00
        sta ZP
        lda src
        sta ZP+1
        lda #ZP
        sta FPTR
        sta SPTR
        ldy #$00
-       ldx #MMU_B0
        jsr FETCH
        pha
        jsr vdc_at
        lda VDATA               ; the VDC's byte to RAM
        ldx #MMU_B0
        jsr STASH
        jsr vdc_at
        pla                     ; RAM's to the VDC
        sta VDATA
        iny
        bne -
        lda #MMU_B1
        sta $ff00
        rts

;;; VDC page vpage -> page dst (bank 0) (subs.128's $7933)
vdc_to_b0:
        lda #MMU_B1IO
        sta $ff00
        lda #$00
        sta ZP
        lda dst
        sta ZP+1
        lda #ZP
        sta SPTR
        ldy #$00
-       jsr vdc_at
        lda VDATA
        ldx #MMU_B0
        jsr STASH
        iny
        bne -
        lda #MMU_B1
        sta $ff00
        rts

;;; VDC address vpage:Y, then the data register selected and ready
vdc_at: ldx #$12
        lda vpage
        jsr vdc_w
        inx
        tya
        jsr vdc_w
        ldx #$1f
        stx VDC
-       bit VDC
        bpl -
        rts
vdc_w:  stx VDC
-       bit VDC
        bpl -
        sta VDATA
        rts

;;; C_B0, copied to common RAM by t7: bank 0, call the driver's stub, back
c_b0:
!pseudopc C_B0 {
        lda C_CFG               ; what the original had when it loaded
        sta $ff00
        jsr U5_C128_LD
        php
        pha
        lda #MMU_B1
        sta $ff00
        pla
        plp
        rts
}
c_b0_end:
!if C_B0 + c_b0_end - c_b0 > $0123 {
        !error "C_B0 runs into $0123, the music's code"
}

src:    !byte 0
dst:    !byte 0
endp:   !byte 0
vpage:  !byte 0
t3mode: !byte 0
t4i:    !byte 0
t4l:    !byte 0
t5new:  !byte 0

;;; ==================================================================
;;; The driver's reads (u5drv.s, C128 build: TC_PICK, TC_FETCH): 2-bit with
;;; the screen on (TC_GUARD's receive, tcguard.s) unless a sprite is
;;; enabled, else 1-bit -- here, in bank 1, because the C128 build of the
;;; driver has 26 bytes free in bank 0.  tclib's pick and every byte come in
;;; through c128fast.s in common RAM, with the MMU at MMU_B1IO (bank 1, I/O
;;; in: the raster and $D015 are read directly), and leave through C_BACK,
;;; which puts MMU_B0 back -- every transfer runs at MMU_B0 (u5_enter).
;;; tclib's banking on the port is whatever its tc_init made it (on a C128
;;; the C64's, bits 0-2 clear), so b1_pick takes the port values from $01
;;; and $00 as tc_enter left them, for both receives, and makes the nibble
;;; table for them (tcfast.s's TC_F_XOR: bits 1-2 of $01 read back into
;;; each nibble).
;;; ==================================================================
CMD_READ_FLASH      = $10
CMD_READ_FLASH_FAST = $11
BIT_SENSE           = $10

b1_pick:
        lda $01                 ; tclib's all-RAM value: write low
        sta tc_v_gio + 1        ; (the guard's "I/O in": no change here)
        sta b1_w0 + 1
        ora #$08
        sta b1_w1 + 1           ; write high
        ora #$10
        sta tc_v_fstart + 1     ; write and sense high: the start
        and #%11110111
        sta tc_v_fend + 1       ; sense high, write low
        lda $00
        sta tc_d_fend + 1       ; tclib's DDR
        and #%11110111
        sta tc_d_fast + 1       ; write as an input
        lda $01
        lsr
        and #$03
        sta b1_flip
        ldx #15
-       txa
        eor b1_flip
        asl
        asl
        asl
        asl
        ora b1_flip
        sta tc_nibbletab,x
        dex
        bpl -
        lda $d015
        bne +
        lda #<tc_getbyte_guard
        ldx #>tc_getbyte_guard
        ldy #CMD_READ_FLASH_FAST
        bne b1_set              ; always
+       lda #<b1_slow
        ldx #>b1_slow
        ldy #CMD_READ_FLASH
b1_set: sta b1_fetch + 1
        stx b1_fetch + 2
        tya                     ; (Y: tclib keeps none across the pick)
        jmp C_BACK

b1_get:
b1_fetch:
        jsr b1_slow             ; patched by b1_pick
        jmp C_BACK

;;; tclib's tc_getbyte, the 1-bit receive, with its values from b1_pick
b1_slow:
        lda #BIT_SENSE
-       bit $01
        beq -
b1_w1:  lda #$00                ; patched: write high
        sta $01
        ldx #$08
        lda #$00
        sta b1_tmp
b1_bit:
b1_w0:  lda #$00                ; patched: write low
        sta $01
        lda b1_w1 + 1
        sta $01
        asl b1_tmp
        lda $01
        and #BIT_SENSE
        beq +
        inc b1_tmp
+       dex
        bne b1_bit
        lda b1_w0 + 1
        sta $01
        lda b1_tmp
        rts
b1_tmp:  !byte 0
b1_flip: !byte 0

TC_GUARD      = 1               ; (for tcfast.s's page check)
TC_GUARD_BARE = 1
TC_F_XOR      = 0               ; EOR and a table b1_pick makes
!source "tcguard.s"

!source "sub128_data.s"         ; letters, first, last, kbuf, tag

!if * > B1_ORG + $1000 {
        !error "sub128.s is past $EFFF"
}
