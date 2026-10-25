;;; u6boot.s -- Ultima 6's boot driver: the resident loader's body, replaced.
;;;
;;; u6load copies a 1 KiB driver to $C000 and starts it at $C00C; the
;;; overlays of the boot phases (opening, character creation, intro) call
;;; its jump table at $C000-$C009.  Everything up to $C16A -- the jump table,
;;; the cold start, the machine setup at $C074, the load descriptors at
;;; $C0B6, the music IRQ at $C12D -- stays; build.py patches three places in
;;; it:
;;;
;;;   $C00C  JSR $C2E4 (upload drive code)  -> three NOPs: the init stub
;;;                                            (init_u6.s) has found the log
;;;   $C071  JMP $0200 (start `game`)       -> JMP ub_handoff: tell `game`'s
;;;                                            own driver where the log is
;;;   $C135  LDA #$35 in the IRQ            -> keep $01 bits 3/4 (TC_IRQ_ON)
;;;
;;; and this replaces $C16B -- the loader, same command strings as `game`'s
;;; (U6 notes 5b) -- through $C3FF, and adds a second piece at $C578-$C7FF,
;;; which a memmap of the opening, character creation and the intro shows
;;; untouched.  Once `game` runs, its overlays load over all of $C000-$CBFF;
;;; the in-game driver (u6res.s + u6bulk.s) takes over, as the original's
;;; second loader did.
;;;
;;; THE WORLD RESET.  The game keeps its world in the chunk files and never
;;; resets them: the manual says to play on fresh copies of the disks.  The
;;; cart's equivalent is an empty write log, and character creation is the
;;; moment: its first write of the save area (track 6 sector 9) erases the
;;; log first, once per boot.

TC_NO_CMDMODE = 1
TC_NO_FAST    = 1
TC_NO_STREAM  = 1               ; the Game disk's files are stored raw: no
                                ; decoder at boot, there is no room for one
TC_IRQ_ON     = 1               ; the theme plays from the IRQ during loads
TC_NO_C0      = 1
TC_STATIC_01  = $35
TC_STATIC_00  = $2f

!source "u6.inc"
U6_OTHER  = ub_other
U6_EXIT01 = $35                 ; the resident loader leaves $01 = $35

LOG_LO   = $ffffff              ; placeholders, see u6_logbase below

        * = $c16b
;;; ==================================================================
;;; $C16B -- the loader.  X/Y -> the command.
;;; ==================================================================
ub_cmd:
        stx u6_c+1
        sty u6_c+2
        stx u6_cmd0
        sty u6_cmd0+1
!source "u6io_read.s"

;;; anything but a plain sector read
ub_other:
        cmp #$23
        beq ub_id
        cmp #$26
        bne ub_core
        ldy #$01                ; &: is it the save area's first sector?
        jsr ub_peek
        cmp #$06
        bne ub_core
        iny
        jsr ub_peek
        cmp #$09
        bne ub_core
        lda ub_fresh            ; creating a character: a fresh world
        bne ub_core
        inc ub_fresh
        jsr ub_reset
ub_core:
        lda u6_cmd0             ; u6core re-reads the command from the start
        sta u6_c+1
        lda u6_cmd0+1
        sta u6_c+2
        jmp b_entry

;;; # -- which disk: SU and DU have sectors, the others are read by name
ub_id:  jsr u6_cb
        tax
        jsr u6_cb               ; the second letter: U for both
        lda #$00
        cpx #$53                ; S
        beq +
        lda #$01
        cpx #$44                ; D
        bne ++
+       sta u6_disk
++      jmp u6_ok

;;; A <- command byte Y (u6_cmd0 + Y), without moving the reader
ub_peek:
        lda u6_cmd0
        sta ub_pk+1
        lda u6_cmd0+1
        sta ub_pk+2
ub_pk:  lda $ffff,y
        rts

!source "u6io_sector.s"

TCLIB_ORG = *
!source "tclib.s"

ub_piece1_end:
!if ub_piece1_end > $c400 {
        !error "u6boot piece 1 runs past $C3FF by ", ub_piece1_end - $c400
}

        * = $c578
!source "u6core.s"
!source "u6io_small.s"

;;; ==================================================================
;;; ub_reset -- erase the whole log region, and start it empty
;;; ==================================================================
ub_reset:
        ;; Both halves (see init_u6.s): the log restarts in half 0, which
        ;; with no header is generation 0.
        ldx #$02
-       lda u6_logbase,x
        sta tc_addr,x
        sta u6_logdata,x
        lda u6_h0top,x
        sta u6_logdir,x
        dex
        bpl -
        lda #$00
        sta u6_dircount
        sta u6_dircount+1
-       jsr tc_erase_block
        clc                     ; the next 4 KiB block
        lda tc_addr+1
        adc #$10
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       lda tc_addr+1
        cmp u6_logtop+1
        bne -
        lda tc_addr+2
        cmp u6_logtop+2
        bne -
        rts

;;; ==================================================================
;;; ub_handoff -- `game` is loaded; its driver learns where the log is
;;; ==================================================================
ub_handoff:
        ldx #$04
-       lda u6_logdir,x         ; logdir (3), dircount (2): adjacent in `game`
        sta G_LOGDIR,x          ; too -- but its logdata is not, so it goes
        dex                     ; separately (writing all eight in one run
        bpl -                   ; clobbered the keyboard scan at $28CE)
        ldx #$02
-       lda u6_logdata,x
        sta G_LOGDATA,x
        dex
        bpl -
        ;; `game`'s one-time init (machine setup, the screen frame: 347 bytes
        ;; of its RAM) runs from a copy in flash, fetched to $4400 -- idle
        ;; until the window loads -- so that those bytes are free in play
        ;; (build.py relocate_init, docs/developer/u6.md).  The copy
        ;; ends in `JMP $03FC`, the main loop's entry, as the original did.
        ldx #$06
-       lda u6_initsrc,x        ; flash address (3), length (2), $4400
        sta tc_addr,x
        dex
        bpl -
        jsr tc_read
        jmp $4400


;;; ---- state ---------------------------------------------------------
u6_initsrc:  !fill 7, $ff       ; filled in by the build (relocate_init)
u6_cmd0:     !word 0
u6_disk:     !byte 0
u6_t:        !byte 0
u6_s:        !byte 0
u6_off:      !byte 0
u6_cnt:      !byte 0
u6_ment:     !fill 4, 0         ; the block map entry: address (3), length
u6_mlen = u6_ment + 3
u6_blk:      !byte 0
u6_map_lo:   !byte $ff, $ff     ; filled in by the build
u6_map_mid:  !byte $ff, $ff
u6_map_hi:   !byte $ff, $ff
u6_sdir:     !fill 5, $ff
u6_logdir:   !fill 3, $ff       ; logdir (3), dircount (2), logdata (3):
u6_dircount: !word $ffff        ; adjacent, in this order, as in `game`
u6_logdata:  !fill 3, $ff
u6_logbase:  !fill 3, $ff       ; the log region: its first page ...
u6_logtop:   !fill 3, $ff       ; ... and its end
u6_h0top:    !fill 3, $ff       ; the top of half 0
ub_fresh:    !byte 0            ; the world has been reset this boot
u6_full:     !byte 0
!if >u6_logdir != >u6_sdir {
        !error "u6_logdir and u6_sdir must share a page"
}

ub_piece2_end:
!if ub_piece2_end > $c800 {
        !error "u6boot piece 2 runs past $C7FF by ", ub_piece2_end - $c800
}
