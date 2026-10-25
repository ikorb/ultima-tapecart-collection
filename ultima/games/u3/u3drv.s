;;; u3drv.s -- Ultima 3 disk driver replacement.
;;;
;;; U3 never calls a loader directly.  It *prints* an Apple DOS 3.3 command
;;; through the character-output vector -- `jsr print / ^D "L MAPA"` -- and the
;;; $B800 module intercepts it, looks the 4-character name up in the catalog at
;;; $B000, and transfers blocks.  All 44 call sites go through one routine,
;;; dos_transfer at $BA48, whose contract is a parameter block at $BB00:
;;;
;;;   $BB00 p_op         1 = load, 2 = save
;;;   $BB01 p_dest_lo    always 0 (loads are page aligned)
;;;   $BB02 p_dest_page
;;;   $BB03 p_block_lo   \  linear disk block on the original;
;;;   $BB04 p_block_hi   /  a FLASH PAGE here, see below
;;;   $BB05 p_length     block count
;;;
;;; The dispatcher copies those straight out of the catalog entry
;;; (+4/+5 start block, +6 length, +7 destination page), and the catalog is
;;; static data loaded from disk at boot.  So build.py rewrites +4/+5 to a
;;; flash page number and this code reads it as one.  catalog_find, the ^D
;;; parser and all 44 call sites are untouched, and -- unlike U4 -- no "which
;;; disk is inserted" notion is needed anywhere, because the catalog entry
;;; already identifies the content uniquely.
;;;
;;; Bit 7 of the length byte (+6) marks a writable entry.  Real lengths are
;;; 1..16 blocks, so the bit is free, and the dispatcher copies it through to
;;; p_length verbatim.
;;;
;;; This lives at $BC00, which the U3 memory map lists as free and which no
;;; catalog entry loads into.  $BA48 is patched to JMP here; the original
;;; dos_transfer body, the track/sector conversion, the geometry table at
;;; $BAD6 and all the KERNAL serial code at $BB0B+ become dead.

TC_NO_CMDMODE = 1               ; the launcher entered it; command mode persists
U3_FAST       = 0               ; 1 = READ_FLASH_FAST + blank, 0 = tc_read
TC_NO_FAST    = 1               ; no blanking: TC_GUARD's tc_read is 2-bit
TC_GUARD      = 1               ; with the screen on (1-bit if a sprite is)
TC_NMI_HOLD   = 1               ; and no RESTORE inside a timed byte
TC_GUARD_ELSEWHERE = 1          ; tcguard.s is in the decoder's segment:
                                ; $BC00-$BFFF has no room for it

;;; the game's parameter block
p_op        = $bb00
p_dest_lo   = $bb01
p_dest_page = $bb02
p_block_lo  = $bb03
p_block_hi  = $bb04
p_length    = $bb05

F_WRITABLE  = %10000000         ; bit 7 of the catalog length byte.  Lengths
                                ; run to 87 blocks (EXOD), so bit 7 is the
                                ; only free one -- bit 6 is already set in 87.
;;; "Stored crunched" therefore lives in the START field instead: it is a
;;; flash page number, and 2 MiB is 8192 pages, so bits 13-15 are spare.
F_COMP      = %10000000         ; bit 15 of the start page, i.e. p_block_hi

;;; The decruncher sits at $C500, which the U3 memory map lists as free
;;; (between DDAT at $C100-$C4FF and UPDT at $CA00) and which a VICE
;;; watchpoint agrees is never written.  It cannot go with the driver: this
;;; area is one page short of holding both.  acme emits one blob spanning
;;; $BC00-$C72C with the hole zero filled, and build.py slices it -- the
;;; hole covers DEMO and DDAT, so writing it back would be fatal, and the
;;; assertion that it is empty is what proves the driver stayed inside
;;; $BC00-$BFFF.
DECODER_ORG = $c500

;;; save slots are two erase blocks each: SOSA is 16 blocks of data, which
;;; with a header page does not fit in one 4 KiB block
SAVE_SLOT_BLOCKS = 2
ERASE_BLOCK = $1000
SAVE_MAGIC0 = $a5
SAVE_MAGIC1 = $5a

        * = $bc00
        jmp u3_transfer         ; $BC00 -- $BA48 is patched to jump here
        jmp tc_init             ; $BC03 -- the launcher calls this once

TCLIB_ORG = $bc06
!source "tclib.s"

;;; ==================================================================
;;; replacement for dos_transfer
;;;
;;; Unlike U1 -- which masks interrupts for its entire run -- U3 plays with
;;; IRQs enabled, and tclib's tc_enter does an SEI that nothing undoes.  So
;;; the caller's I flag has to be put back.  PHP/PLP would do it but would
;;; also clobber the carry, so save just the status byte and re-CLI by hand.
;;; ==================================================================
u3_transfer:
        jsr st_flush            ; a footstep's clicks first (u3step.s)
        php
        pla
        sta u3_flags
        jsr u3_transfer_i
        php                     ; (its carry is the caller's)
        jsr pt_apply            ; the launcher's options (asm/patch.s)
        jsr u3_opt_once
        plp
        lda u3_flags
        and #%00000100          ; caller's I flag
        bne +
        cli
+       rts

u3_transfer_i:
        lda p_length
        and #F_WRITABLE
        sta u3_writable
        lda p_block_hi
        and #F_COMP
        sta u3_crunched
        lda p_length
        ;; NB: acme's "^" is the bank-byte operator, not XOR -- writing
        ;; "#<(F_WRITABLE ^ $ff)" here silently assembles as "and #$00",
        ;; which makes every load a no-op.  Spell the mask out.
        and #%01111111          ; block count, without the writable flag
        sta u3_blocks
        beq u3_ret              ; zero blocks: nothing to do

        ;; remember the slot base page; tc_addr gets rewritten below
        lda p_block_lo
        sta u3_base
        lda p_block_hi
        and #%01111111          ; without the crunched flag
        sta u3_base+1

        lda p_op
        cmp #$02
        beq u3_do_save

;;; ---- load --------------------------------------------------------
        lda u3_writable
        beq u3_load_plain

        ;; writable entry: the data sits one page into the slot, behind a
        ;; header that says whether a save is actually there
        jsr u3_read_header
u3_hdr_done:
        lda u3_hdr+0
        cmp #SAVE_MAGIC0
        bne u3_ret              ; no save: leave memory as it is
        lda u3_hdr+1
        cmp #SAVE_MAGIC1
        bne u3_ret
        jsr u3_addr_data
u3_magic_ok:
        jmp u3_load_go

u3_load_plain:
        jsr u3_addr_base
u3_load_go:
        jsr u3_set_dest
        lda u3_crunched
        beq +
        jsr u3_unpack           ; length comes from the blob itself
        rts
+       jsr u3_set_len
        jsr u3_xfer
u3_ret:
        rts

;;; The crunched path needs no blanking: the 1-bit protocol has no timing
;;; constraint, so a compressed load is also a load without the flicker.
;;; $01 still has to have I/O in for nothing here, but force CHAREN anyway
;;; rather than depend on the game's discipline -- never LORAM, which would
;;; bank BASIC ROM over this code.
u3_unpack:
        lda $01
        sta u3_save01
        ora #%00000110
        sta $01
        jsr zxd_unpack_sized
        lda u3_save01
        sta $01
        rts

;;; ---- save --------------------------------------------------------
u3_do_save:
        lda u3_writable
        beq u3_ret              ; read-only entry: silently ignore
        ;; through the journal (asm/journal.s): the slot written there first,
        ;; then in place
        jsr u3_addr_base
        jsr jr_begin
        jsr u3_base_from_addr
        jsr u3_sv_body
        jsr jr_commit
        jsr u3_base_from_addr
        jsr u3_sv_body
        jmp jr_end

u3_base_from_addr:              ; u3_base <- tc_addr: where u3_sv_body writes
        lda tc_addr+1
        sta u3_base
        lda tc_addr+2
        sta u3_base+1
        rts

u3_sv_body:
        ;; Erase exactly the blocks this write will cover -- one header page
        ;; plus the data, rounded up to 4 KiB (16 pages).  Only SOSA (16
        ;; blocks) needs two; erasing blindly costs flash endurance and, on
        ;; a 1-block slot, would erase a block we never write.
        lda u3_blocks
        clc
        adc #$01                ; the header page
        clc
        adc #$0f
        lsr
        lsr
        lsr
        lsr                     ; / 16 pages per erase block
        sta u3_erases
        jsr u3_addr_base
u3_er_loop:
        jsr tc_erase_block
        lda tc_addr+1
        clc
        adc #>ERASE_BLOCK
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       dec u3_erases
        bne u3_er_loop
u3_sv_erased:

        ;; write the data a page in
        jsr u3_addr_data
        jsr u3_set_len
        jsr u3_set_dest         ; tc_write reads from tc_dest
        jsr tc_write
u3_sv_written:

        ;; header last, so a power cut leaves the slot reading as empty
        lda #SAVE_MAGIC0
        sta u3_hdr+0
        lda #SAVE_MAGIC1
        sta u3_hdr+1
        lda u3_blocks
        sta u3_hdr+2
        lda #$00
        sta u3_hdr+3
        jsr u3_addr_base
        jsr u3_hdr_len_dest
        jmp tc_write

;;; ==================================================================
;;; helpers
;;; ==================================================================
u3_addr_base:
        lda #$00
        sta tc_addr
        lda u3_base
        sta tc_addr+1
        lda u3_base+1
        sta tc_addr+2
        rts

u3_addr_data:
        jsr u3_addr_base
        inc tc_addr+1           ; one page in
        bne +
        inc tc_addr+2
+       rts

u3_read_header:
        jsr u3_addr_base
        jsr u3_hdr_len_dest
        jmp tc_read

u3_hdr_len_dest:
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<u3_hdr
        sta tc_dest
        lda #>u3_hdr
        sta tc_dest+1
        rts

;; tc_len = blocks * 256
u3_set_len:
        lda #$00
        sta tc_len
        lda u3_blocks
        sta tc_len+1
        rts

;; tc_dest = p_dest_page << 8 (p_dest_lo is always 0)
u3_set_dest:
        lda p_dest_lo
        sta tc_dest
        lda p_dest_page
        sta tc_dest+1
        rts

;;; The fast protocol needs the display quiet; tc_blank waits the frame out.
;;; U3 runs permanently at $01 = $36 so I/O is always in, but force it anyway
;;; rather than depend on that.
u3_xfer:
        lda $01
        sta u3_save01
        ;; Force I/O visible with HIRAM+CHAREN and never LORAM: LORAM banks
        ;; BASIC ROM in over $A000-$BFFF.  Harmless for U1's driver at $C000,
        ;; fatal for U3's at $BC00 -- the driver would vanish mid-routine.
        ora #%00000110
        sta $01
!if U3_FAST = 1 {
u3_xfer_go:
        jsr tc_blank
        jsr tc_read_fast
        jsr tc_unblank
} else {
        jsr tc_read
}
        lda u3_save01
        sta $01
        rts

u3_base:     !byte 0,0
u3_blocks:   !byte 0
u3_writable: !byte 0
u3_crunched: !byte 0
u3_save01:   !byte 0
u3_flags:    !byte 0
u3_erases:   !byte 0
u3_hdr:      !byte 0,0,0,0

u3_drv_end:
!if u3_drv_end > $c000 {
        !error "u3 driver overruns DEMO at $C000 by ", u3_drv_end - $c000, " bytes"
}

;;; ==================================================================
        * = DECODER_ORG
!source "zxdecr.s"
!source "patch.s"
;;; Journey onward is for the one launch: once BOOT's menu has the patch
;;; (JMP $12A9 at $1278), the bit goes, so a BOOT loaded later is BOOT.
u3_opt_once:
        lda $1278
        cmp #$4c
        bne +
        lda pt_opts
        and #%11111011
        sta pt_opts
+       rts
pt_opts: !byte 0                ; the launcher pokes it: patches.py's bits
pa_on:   !byte 0
pa_n:    !byte 0
pa_x:    !byte 0
!source "u3_patches.s"          ; generated by build.py: PT_TAB
!source "tcguard.s"             ; TC_GUARD's receive (see above)
!source "u3key.s"               ; SUBS' key wait: type-ahead and joystick 2
!source "u3step.s"              ; the footstep's clicks from the IRQ
!source "u3view.s"              ; UPDT's line of sight in one pass
!source "u3trainer.s"           ; Gold's ingame keys, behind the launcher's X
!source "u3avoid.s"             ; "AVOID?", the launcher's A
!source "journal.s"             ; JOURNAL from build.py (regions.journal)
u3_zx_end:
!if u3_zx_end > $ca00 {
        !error "u3 decoder overruns UPDT at $CA00"
}
