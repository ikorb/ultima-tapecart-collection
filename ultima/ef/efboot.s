;;; efboot.s -- Ultima VI's boot driver on EasyFlash: the resident loader's
;;; body, replaced (as ultima/games/u6/u6boot.s does on the tapecart).
;;;
;;; u6load's 1 KiB at $C000 stays up to $C16A -- the jump table, the cold
;;; start, the machine setup at $C074, the load descriptors at $C0B6, the
;;; music IRQ at $C12D -- with two patches (ultima/ef/build.py): the cold start's
;;; drive-code upload NOPed, and its `JMP $0200` into `game` turned into
;;; `JMP ub_handoff`.  The rest is this: the trampoline at $C16B, the loader's
;;; entry, and what has to be RAM for the driver in ROM (efdrv.s, EF_BOOT),
;;; in $C16B-$C3FF and $C578-$C7FF (idle in memmaps of the opening, character
;;; creation and the intro).  The IRQ is the resident's own, at $C12D, which
;;; banks with `LDA #$35 / STA $01` and so hides the cart while it plays.
;;;
;;; EAPI's slot at boot is $5800-$5AFF, inside CREATE's image but untouched
;;; in the creation memmap (`$566B-$63DF`, build/u6_mm_create.bmp) and named
;;; by no instruction that ran; writes come only from character creation
;;; (the world reset and the new party's save area), and e_end puts CREATE's
;;; bytes back from its file in flash.

!source "efvars.inc"

        * = $c16b
;;; ==================================================================
;;; $C16B -- the loader.  X/Y -> the command.
;;; ==================================================================
ub_cmd:
        stx k_c+1
        sty k_c+2
        lda #$00                ; efdrv's entry 0: a command
        beq ub_go
;;; `game` is loaded ($C071, instead of `JMP $0200`): its one-time init comes
;;; from flash to INIT_AT (efdrv's entry 1), and runs from there
ub_handoff:
        lda #$03
        jsr ub_go
        jmp INIT_AT

;;; $C054, Journey onward's way into the game ($C054 JSR $C074 made JSR
;;; here): the machine setup, then the display off.  The setup stops the
;;; opening's raster split, so the VIC stays on its bank 2 -- the picture's
;;; bitmap at $A000, its colours at $8C00 -- which the next loads (COLORS to
;;; $A000, TILEFLAGS after it, TILES over $6000-$9FFF) overwrite.  On disk
;;; those take seconds, behind the picture; here the screen would show the
;;; garbage instead, so it is blanked.  `game` turns the display on
;;; again with its own raster split.
ub_journey:
        jsr $c074
        lda $d011
        and #%11101111
        sta $d011
        rts

ub_go:  sta ub_jsr+1
        php
        pla
        sta g_p
        sei
        lda $0314
        sta g_v
        lda $0315
        sta g_v+1
        lda #<k_shim
        sta $0314
        lda #>k_shim
        sta $0315
        lda $fffe               ; ($01 has HIRAM clear: the RAM vector)
        sta k_shj+1
        lda $ffff
        sta k_shj+2
        lda #$37
        sta $01
        lda #DRVBANK
        sta EF_BANK_REG
        lda #EF_16K_LED
        sta EF_CTRL_REG
        lda g_p
        pha
        plp
ub_jsr: jsr $8000
        sei
        lda #EF_OFF
        sta EF_CTRL_REG
        lda #$35                ; as the resident loader left it
        sta $01
        lda g_v
        sta $0314
        lda g_v+1
        sta $0315
        lda g_p
        and #$fe
        adc #$00
        pha
        plp
        rts

k_shim: pla
        tay
        pla
        tax
        pla
k_shj:  jmp $ffff

k_cb:
k_c:    lda $ffff
        inc k_c+1
        bne +
        inc k_c+2
+       rts

k_run:  sta EF_BANK_REG
        php
        ldx k_hz                ; a run into page 3 (a program loading at
        beq +                   ; $0200): ($0314) holds the program's own
        sei                     ; bytes while it runs, interrupts off, and
        lda g_v                 ; what it leaves there is what the way out
        sta $0314               ; puts back (g_v)
        lda g_v+1
        sta $0315
+       lda #$33
        sta $01
        ldy #$00
k_rs:   lda $ffff,y
k_rd:   sta $ffff,y
        iny
k_rn:   cpy #$00
        bne k_rs
        lda #$37
        sta $01
        cpx #$00
        beq +
        lda $0314
        sta g_v
        lda $0315
        sta g_v+1
        lda #<k_shim
        sta $0314
        lda #>k_shim
        sta $0315
+       plp
        lda #DRVBANK
        sta EF_BANK_REG
        rts
k_hz:   !byte 0

k_cmp:  sta EF_BANK_REG
        ldy #$00
-       lda d_keybuf,y
k_cp:   cmp $ffff,y
        bne +
        iny
        cpy #KEYLEN
        bne -
+       php
        lda #DRVBANK
        sta EF_BANK_REG
        plp
        rts

e_init:
        lda #$35                ; the latching NMI goes through the RAM
        sta $01                 ; vector: the resident's RTI at $C164
        lda #$7f
        sta $dd0d
        lda $dd0d
        lda #$01
        sta $dd04
        lda #$00
        sta $dd05
        lda #$81
        sta $dd0d
        lda #$19
        sta $dd0e
        nop
        nop
        nop
        nop
        lda #$37
        sta $01
        jsr EAPI_SLOT + EAPI_INIT_OFF
e_tail: php
        pha
        lda #DRVBANK
        sta EF_BANK_REG
        lda #EF_16K_LED
        sta EF_CTRL_REG
        pla
        plp
        rts

e_write:
        jsr EAPI_SETBANK
        lda #EAPI_LHLH
        jsr EAPI_SETPTR
        ldy #$00
e_wl:   lda #$34
        sta $01
e_ws:   lda $ffff,y
        ldx #$37
        stx $01
        jsr EAPI_WRITEINC
        bcs e_wx
        iny
e_wn:   cpy #$00
        bne e_wl
        clc
e_wx:   jmp e_tail

e_erase:
        jsr EAPI_ERASE
        jmp e_tail

ub_piece1_end:
!if ub_piece1_end > $c400 {
        !error "efboot piece 1 runs past $C3FF by ", ub_piece1_end - $c400
}

        * = $c578
;;; ---- the driver's variables (efdrv.s) --------------------------------
d_disk:   !byte 0
d_t:      !byte 0
d_s:      !byte 0
d_off:    !byte 0
d_cnt:    !byte 0
d_tmp:    !byte 0
d_run:    !byte 0
d_term:   !byte 0
d_ment:   !fill 4, 0
d_keybuf: !fill KEYLEN, 0
d_data:   !fill DATALEN, 0
d_ent:    !fill DATALEN, 0
d_ra:     !fill 3, 0
d_rl:     !word 0
d_rd:     !word 0
d_dst:    !word 0
d_w:      !fill 3, 0
d_n:      !word 0
d_kt:     !fill KEYLEN, 0
d_lo:     !word 0
d_hi:     !word 0
d_mid:    !word 0
d_t4:     !word 0
d_p:      !word 0
d_wsrc:   !word 0
d_wn:     !byte 0
d_wa:     !fill 3, 0
d_left:   !byte 0
g_p:      !byte 0
g_v:      !word 0

ub_piece2_end:
!if ub_piece2_end > $c800 {
        !error "efboot piece 2 runs past $C7FF by ", ub_piece2_end - $c800
}
