;;; efres.s -- Ultima VI's in-game driver on EasyFlash: what has to be RAM.
;;;
;;; Lives where the tapecart build's resident does, in `game`'s own disk code
;;; (the old loader at $2989-$2B4D, the disk check and swap prompt at
;;; $2823-$28CD), plus the room the relocated init and the absent REU cache
;;; leave ($132E-$13D9).  The entry points stay where the game calls them:
;;;
;;;   $29BE  the loader: X/Y -> a command string (U6 notes 5b), also through
;;;          $0263 and from $27FA/$2804/$2809
;;;   $2823  "is disk X in?": every disk is in flash, so remember which
;;;   $29B6  a lone RTS ($02AE in the jump table is JMP $29B6): k_cb's
;;;
;;; Everything else -- the commands, the directories, the log -- is efdrv.s
;;; in the cart's ROM, bank DRVBANK, which the trampoline here calls with
;;; the cart in 16K mode and $01 = $37.  That banks the KERNAL in too, and
;;; the KERNAL's IRQ entry jumps through ($0314) -- which in `game` is the
;;; jump table's entry at $0314 (4C 64 31: an IRQ would go to $644C, the
;;; tiles).  So for as long as the cart is in, ($0314) points at k_shim,
;;; which drops what the KERNAL pushed and enters the game's own handler,
;;; whose `LDA #$35 / STA $01` hides cart and KERNAL until its `RTI` puts
;;; $01 back.  RESTORE cannot get in: e_init latches CIA 2's NMI before
;;; EAPI ever runs, and `game`'s NMI is an RTI anyway.

!source "efvars.inc"

;;; the access light, as the tapecart's (ultima/games/u6/u6.inc): the frame cell
;;; below the cursor turns white for as long as the driver runs
LIGHT_CELL = $cc00 + 24 * 40 + 23
LIGHT_ON   = $81
LIGHT_OFF  = $89

        * = $2823
;;; ==================================================================
;;; $2823 -- X = 0 Surface, 2 Dungeon, 4 CA, 6 CB, 8 CC, 10 GA
;;; ==================================================================
u6_setdisk:
        cpx #$04                ; only Surface and Dungeon have sectors;
        bcs +                   ; the other disks are read by name
        txa
        lsr
        sta d_disk
+       clc                     ; the right disk is always in
        rts

;;; ---- the driver's variables (efdrv.s) --------------------------------
d_disk:   !byte 0
d_t:      !byte 0
d_s:      !byte 0
d_off:    !byte 0
d_cnt:    !byte 0
d_tmp:    !byte 0
d_run:    !byte 0
d_term:   !byte 0
d_ment:   !fill 4, 0            ; a block map entry: address (3), mark
d_keybuf: !fill KEYLEN, 0       ; a directory entry being written: key,
d_data:   !fill DATALEN, 0      ; then data
d_ent:    !fill DATALEN, 0      ; a found entry's data
d_ra:     !fill 3, 0            ; fl_read: from (linear), how many, to --
d_rl:     !word 0               ;   d_ra and d_rl adjacent (d_entrd)
d_rd:     !word 0
d_dst:    !word 0
d_w:      !fill 3, 0            ; the log's directory walk
d_n:      !word 0
d_kt:     !fill KEYLEN, 0
d_lo:     !word 0               ; the static directory's binary search
d_hi:     !word 0
d_mid:    !word 0
d_t4:     !word 0
d_p:      !word 0
d_wsrc:   !word 0               ; e_put: from, how many, to (linear)
d_wn:     !byte 0
d_wa:     !fill 3, 0
d_left:   !byte 0               ; d_unlink
d_pa:     !fill 3, 0
d_sv:     !word 0
d_link:   !word 0
d_j:      !byte 0               ; d_flush, d_oldpg
d_j2:     !byte 0
d_links:  !fill MAXHOLD * 2, 0  ; the link bytes of the pages held back
g_p:      !byte 0               ; the trampoline: the caller's flags,
g_v:      !word 0               ;   and what $0314/$0315 held

piece_a_end:
!if piece_a_end > $28ce {
        !error "piece A runs into the keyboard scan at $28CE by ", piece_a_end - $28ce
}

;;; ==================================================================
;;; piece B: $2989-$2B4D, k_cb's RTS at $29B6, the entry at $29BE
;;; ==================================================================
        * = $2989

;;; compare d_keybuf with KEYLEN bytes at k_cp in bank A: Z set if equal;
;;; if not, C set when the key is the greater (the first byte that differs)
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

!if * > $29b6 - 11 {
        !error "piece B's start runs into k_cb by ", * - ($29b6 - 11)
}
        !fill $29b6 - 11 - *, $ea
;;; A <- the next byte of the command (keeps X and Y)
k_cb:
k_c:    lda $ffff
        inc k_c+1
        bne +
        inc k_c+2
+       rts
!if * != $29b7 {
        !error "k_cb's RTS is not at $29B6"
}
        !fill $29be - *, $ea

;;; ==================================================================
;;; $29BE -- the loader.  X/Y -> the command.
;;; ==================================================================
u6_cmd:
        stx k_c+1
        sty k_c+2
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
        lda #LIGHT_ON
        sta LIGHT_CELL
        lda g_p                 ; interrupts as the caller had them
        pha
        plp
        jsr $8000
        sei                     ; (C is the result)
        lda #LIGHT_OFF
        sta LIGHT_CELL
        lda #EF_OFF
        sta EF_CTRL_REG
        lda #$34                ; as the original loader left it
        sta $01
        lda g_v
        sta $0314
        lda g_v+1
        sta $0315
        lda g_p                 ; the caller's flags, the result's carry
        and #$fe
        adc #$00
        pha
        plp
        rts

;;; the KERNAL's IRQ entry pushed A, X, Y: drop them, into the game's own
k_shim: pla
        tay
        pla
        tax
        pla
k_shj:  jmp $ffff

;;; copy k_rn bytes (0 = 256) from k_rs in bank A to k_rd, at $01 = $33:
;;; reads see the cart (and the KERNAL, the character ROM), every store goes
;;; to RAM -- under I/O too.  (k_rp+1 = $34 for a copy from RAM under I/O or
;;; the KERNAL; whoever sets it puts $33 back.)
k_run:  sta EF_BANK_REG
        php
        ldx k_hz                ; a run into page 3 (a program loading at
        beq +                   ; $0200): ($0314) holds the program's own
        sei                     ; bytes while it runs, interrupts off, and
        lda g_v                 ; what it leaves there is what the way out
        sta $0314               ; puts back (g_v)
        lda g_v+1
        sta $0315
+
k_rp:   lda #$33
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

;;; a conversation: zx02 from k_gbp in bank k_gbank to zx_put's operand.
;;; The decoder is RAM, so the stream's bank stays in for the whole of it.
k_zx:   lda k_gbank
        sta EF_BANK_REG
        jsr zx_unpack
        lda #DRVBANK
        sta EF_BANK_REG
        rts

;;; zx02's input: the next byte of the stream; keeps X, Y, C and V
;;; (zx02a.s's contract: INC touches only N and Z)
k_gb:
k_gbp:  lda $ffff
        inc k_gbp+1
        beq +
        rts
+       php                     ; a new page, perhaps a new bank
        pha
        inc k_gbp+2
        lda k_gbp+2
        cmp #$c0
        bne +
        lda #$80
        sta k_gbp+2
        inc k_gbank
        lda k_gbank
        sta EF_BANK_REG
+       pla
        plp
        rts
k_gbank: !byte 0

zx_getbyte = k_gb
!source "zx02a.s"

piece_b_end:
!if piece_b_end > $2b4e {
        !error "piece B runs past $2B4D by ", piece_b_end - $2b4e
}

;;; ==================================================================
;;; the init's room at $132E-$13D9: EAPI's callers
;;; ==================================================================
        * = $132e

;;; EAPI has just been copied into the slot: latch CIA 2's NMI (one timer
;;; underflow, never acknowledged, holds the line low, so neither it nor
;;; RESTORE can raise another while EAPI's Ultimax windows are open -- their
;;; vectors would come from whatever bank is selected), then EAPIInit.  C set
;;; if the flash is not one this EAPI knows (A = why).
e_init:
        lda #$35                ; the latching NMI goes through the RAM
        sta $01                 ; vector: `game`'s RTI at $2062
        lda #$7f
        sta $dd0d
        lda $dd0d
        lda #$01
        sta $dd04
        lda #$00
        sta $dd05
        lda #$81
        sta $dd0d
        lda #$19                ; force load, one shot, start
        sta $dd0e
        nop
        nop
        nop
        nop
        lda #$37
        sta $01
        jsr EAPI_SLOT + EAPI_INIT_OFF
e_tail: php                     ; EAPI leaves its bank and $DE02 = $07
        pha
        lda #DRVBANK
        sta EF_BANK_REG
        lda #EF_16K_LED
        sta EF_CTRL_REG
        pla
        plp
        rts

;;; write e_wn bytes (0 = 256) from e_ws (any RAM: read at $01 = $34) to
;;; flash: A = the bank, X/Y = the address in it ($8000-$BFFF).  C set if
;;; a byte would not program.
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

;;; erase a 64 KiB sector: A = its first bank, Y = $80 (ROML) or $E0 (ROMH)
e_erase:
        jsr EAPI_ERASE
        jmp e_tail

;;; Z set if k_qn bytes (0 = 256) at k_qa equal those at k_qb: both RAM,
;;; read at $01 = $34 (a page the game writes may be under I/O)
k_eq:   ldx #$34
        stx $01
        ldy #$00
k_qa:   lda $ffff,y
k_qb:   cmp $ffff,y
        bne +
        iny
k_qn:   cpy #$00
        bne k_qa
        dex                     ; $33: all equal
+       lda #$37
        sta $01
        cpx #$33
        rts

room_end:
!if room_end > $13da {
        !error "the EAPI callers run past $13D9 by ", room_end - $13da
}
