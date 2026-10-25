;;; u6reu.s -- an optional REU (Commodore 1700/1764/1750, 256 KB or more) as a
;;; read cache for the raw sector pages.
;;;
;;; Most of what makes Ultima 6 pause is flash reads at ~2.8 KB/s: a large
;;; overlay (Cast, Talk, combat) is 3 KB, 1.1 s every time it is used; the
;;; tiles' 6 KB reload when a conversation ends; each chunk fetch reads 64
;;; bytes four times.  All of these are sector reads, `^ t s off cnt`,
;;; from the raw sector pages the build lays out in one block of flash
;;; (RC_BASE, RC_PAGES pages), and all of them end in tc_read.
;;;
;;; The hook is tc_read's first instruction, `JSR tc_enter`: it becomes `JMP
;;; rc_read`.  A read of a whole page (256 bytes from its start) inside the
;;; block is looked up: the REU holds a copy of the block (page n at n x 256:
;;; banks 0 to 2) and, in bank 3, one byte a page (non-zero: held).  Held: the
;;; bytes come by DMA (~100 cycles + 1 a byte, the cart not touched, its LED
;;; dark).  Not held: the read goes to the cart as before, and then the page
;;; is stashed in the REU and flagged.  (The 64-byte chunk reads are not
;;; taken: quarter-page flags did not fit.)  Everything else -- the block
;;; map entries (4 bytes), the bulk code, the write log (outside the block,
;;; and its pages are rewritten at a compaction), odd reads -- is passed on
;;; untouched.  Pages of the block are immutable (a sector the game also
;;; writes is read from the log first, by u6bulk; only its unlogged original
;;; comes here).
;;;
;;; rc_on is 0 until the init finds an REU (reu_init, run from the relocated
;;; init: a 256 KB bank test and a DMA round trip, then the flags cleared:
;;; the REU's contents from another session or another cart are never trusted).
;;; Without one, or with something else at $DF00 (an Action Replay's RAM
;;; answers its address registers but moves no data), the hook is one LDA and
;;; a BEQ.  The REU's registers are at $DF00, I/O: the game runs with it
;;; banked out ($01 = $34), so they are set with INC $01 ($35) ... DEC $01.
;;;
;;; **The transfer itself must run with the I/O banked out.**  The REU's DMA
;;; goes through the C64's address decoding: with I/O in, a fetch into
;;; $D000-$DFFF writes the VIC, SID and CIAs, and a stash from there reads
;;; them.  Pages the game reads there: overlay $34 (1A T19 S8-9 to
;;; $D400-$D5FF, the whole window's reload at $2627 -- a moongate, a level
;;; change, a load), the save's BAM (to $D500) and save-area sectors (to
;;; $D600/$D700).  Starting every DMA at once ($90/$91) with $01 = $35 would
;;; leave the save's BAM in $D500 when a later reload of overlay $34 came
;;; from the REU, and the game would run into the BAM.  So the command is only
;;; armed ($80/$81: bit 4 clear) and the transfer starts at a write to
;;; $FF00, which rc_dma does with $01 = $34, every address RAM.
;;;
;;; The code is in the room the one-time init leaves (build.py).
;;;
;;; With an REU the on-demand code is not u6bulk but its two parts, A and B
;;; (u6core.s, u6wc.s), and B keeps a copy of what it last wrote to the log
;;; in the REU, so that a save need not write what has not changed: the init
;;; points the resident at part A, and B's state lives here (wc_*).

!source "u6res_syms.inc"        ; generated: tc_read, tc_enter, tc_addr, tc_len, tc_dest
!source "u6.inc"                ; the REU's commands and its layout

REU_CMD   = $df01
REU_REGS  = $df02               ; C64 address (2), REU address (3), length (2)
REU_CTRL  = $df0a

        * = tc_read
        jmp rc_read             ; was JSR tc_enter

;;; ---- state (the init's room at $2077) --------------------------
        * = RC_VARS
rc_on:  !byte 0                 ; 1: an REU is there and the cache works
rc_c64: !word 0                 ; the seven registers, in the REU's order
rc_ra:  !byte 0, 0, 0
rc_ln:  !word 0
rc_rel: !word 0                 ; the page's number in the block
rc_fl:  !byte 0                 ; its flag
rc_vars_end:

;;; ---- the hook ---------------------------------------------------
;;; Only whole pages: 256 bytes from a page's start (a sector read with
;;; count 0 -- an overlay's sectors, the tiles' reload, ...).  The 64-byte
;;; chunk reads and every other odd read go on to the cart as before.
        * = RC_CODE
rc_read:
        lda rc_on
        bne rc_try
rc_plain:
        jsr tc_enter            ; the original tc_read
        jmp tc_read+3
rc_try: lda tc_len
        ora tc_addr
        bne rc_plain            ; 256 bytes, from a page's start
        lda tc_len+1
        cmp #$01
        bne rc_plain
        sec                     ; the page's number in the block
        lda tc_addr+1
        sbc #<RC_BASE
        sta rc_rel
        lda tc_addr+2
        sbc #>RC_BASE
        sta rc_rel+1
        bcc rc_plain            ; below it
        lda rc_rel
        cmp #<RC_PAGES
        lda rc_rel+1
        sbc #>RC_PAGES
        bcs rc_plain            ; or above
        ldx #REU_FETCH
        jsr rc_flag             ; is the page held?
        lda rc_fl
        beq rc_miss
        dec tc_len+1            ; as tc_read leaves it: the length used up
        ldx #REU_FETCH          ; (tc_dest it leaves alone)
        jmp rc_data             ; yes: its data, by DMA
rc_miss:
        jsr tc_enter            ; no: from the cart,
        jsr tc_read+3
        ldx #REU_STASH
        jsr rc_data             ; into the REU
        inc rc_fl               ; (0 here)
        ldx #REU_STASH
        jmp rc_flag             ; and held

;;; the page's flag byte <-> rc_fl, REU bank 3 at the page's number
rc_flag:
        lda #<rc_fl
        sta rc_c64
        lda #>rc_fl
        sta rc_c64+1
        lda rc_rel
        sta rc_ra
        lda rc_rel+1
        sta rc_ra+1
        lda #RC_FLAGBANK
rc_set1:
        sta rc_ra+2
        lda #$01
        sta rc_ln
        lda #$00
        sta rc_ln+1
;;; the seven registers set and the transfer made; X = the command.  Entered
;;; and left with $01 = $34.
rc_dma: inc $01                 ; the registers: I/O in
        ldy #$06
-       lda rc_c64,y
        sta REU_REGS,y
        dey
        bpl -
        stx REU_CMD             ; armed
        dec $01                 ; I/O out: the DMA sees RAM everywhere
        lda $ff00
        sta $ff00               ; the transfer happens here, the CPU halted
        rts

;;; ---- the write cache's state (u6wc.s): it outlives part B's calls ----
wc_bheld:  !byte 0, 0           ; part B for $D800, $DC00 is in the REU
wc_spage:  !byte 0              ; the open session's file: its slot (page,
wc_sbank:  !byte 0              ;   bank), its size in pages, its count's
wc_cap:    !byte 0              ;   index (u6.inc)
wc_ix:     !byte 0
wc_old:    !byte 0              ; the count: pages the slot holds, 0 none
wc_held:   !byte 0              ; pages held back, all as the log has them;
                                ; $FF: written as they come
;;; A <- the REU's status (which clears its verify error).  Here, not in
;;; part B: with I/O banked in, $D000-$DFFF is I/O, so no code may run from
;;; the sprite halves between the INC and the DEC (the first version did,
;;; and fetched its next instruction from the I/O area: a crash in VICE).
rc_status:
        inc $01
        lda REU_STATUS
        dec $01
        rts
rc_code_end:

;;; the page's data <-> the C64 at tc_dest, in the other piece of room
        * = RC_CODE2
rc_data:
        lda tc_dest
        sta rc_c64
        lda tc_dest+1
        sta rc_c64+1
        lda #$00
        sta rc_ra
        sta rc_ln
        lda rc_rel
        sta rc_ra+1
        lda rc_rel+1
        sta rc_ra+2
        lda #$01
        sta rc_ln+1
        jmp rc_dma
rc_end:
!if rc_code_end > RC_CODE + 172 {
        !error "u6reu.s: the first piece runs past its room by ", rc_code_end - RC_CODE - 172
}
!if rc_end > RC_CODE2 + 51 {
        !error "u6reu.s: the second piece runs past its room by ", rc_end - RC_CODE2 - 51
}

;;; ---- the init's part: find the REU (in the relocated init's blob) ----
;;; Run with $01 = $34.  Leaves rc_on = 1 and the flags cleared, or 0.
;;; (rc_dma banks the I/O in and out itself: it is called with $01 = $34.)
        * = RC_INIT
reu_init:
        lda #$00
        sta rc_on
        inc $01
        ldx #$03                ; 1. the address registers hold what is written
-       txa                     ;    (an unaddressed bus answers with itself)
        eor #$a5
        sta REU_REGS,x
        dex
        bpl -
        ldx #$03
-       txa
        eor #$a5
        cmp REU_REGS,x
        bne ri_no
        dex
        bpl -
        dec $01
        lda #$a5                ; 2. data moves, and bank 3 is not bank 1 (a 128 KB
        sta rc_fl             ;    REU has two banks): stash $A5 in bank 3, $5A in
        lda #$03                ;    bank 1, fetch bank 3's
        ldx #REU_STASH
        jsr ri_one
        lda #$5a
        sta rc_fl
        lda #$01
        ldx #REU_STASH
        jsr ri_one
        lda #$03
        ldx #REU_FETCH
        jsr ri_one
        lda rc_fl
        cmp #$a5
        bne ri_out              ; (an Action Replay's RAM keeps $5A: no DMA)
        lda #$00                ; 3. every page unheld: bank 3 cleared, RC_PAGES
        sta rc_fl               ;    bytes of it, from the one zero byte
        inc $01
        lda #$80
        sta REU_CTRL            ;    (the C64's address fixed)
        dec $01
        lda #<rc_fl
        sta rc_c64
        lda #>rc_fl
        sta rc_c64+1
        lda #$00
        sta rc_ra
        sta rc_ra+1
        lda #RC_FLAGBANK
        sta rc_ra+2
        lda #<WC_CLEAR          ;    (and the write cache's counts: no copy
        sta rc_ln               ;    of anything is trusted from before)
        lda #>WC_CLEAR
        sta rc_ln+1
        ldx #REU_STASH
        jsr rc_dma
        inc $01
        lda #$00
        sta REU_CTRL
        sta $df09               ; no interrupts from it
        lda REU_STATUS          ; (reading it clears a verify error)
        dec $01
        jmp ri_check            ; 4. the write cache only if verify works
ri_out: jmp $03fc               ; the init's end
ri_no:  dec $01
        jmp $03fc
;;; one byte, rc_fl <-> REU bank A, address 0; X = the command
ri_one: sta rc_ra+2
        lda #<rc_fl
        sta rc_c64
        lda #>rc_fl
        sta rc_c64+1
        lda #$00
        sta rc_ra
        sta rc_ra+1
        sta rc_ln+1
        lda #$01
        sta rc_ln
        jmp rc_dma
;;; 4. verify, as the launcher's page tests it (asm/page_reu.s, which says
;;;    so when it fails): a page -- this one, the init's own code, which
;;;    stays as it is -- to REU $000000 (the read cache's page 0, its flag
;;;    clear), then compared: the same (no error), its last byte different
;;;    there, its first (an error each).  C clear if it works.
RI_P = reu_init & $ff00
ri_verify:
        lda #REU_STASH
        jsr ri_page
        lda #REU_VERIFY
        jsr ri_page
        bne ri_vbad
        lda RI_P+255
        eor #$ff
        ldy #$ff
        jsr ri_poke
        lda #REU_VERIFY
        jsr ri_page
        beq ri_vbad
        lda RI_P+255
        ldy #$ff
        jsr ri_poke
        lda RI_P
        eor #$ff
        ldy #$00
        jsr ri_poke
        lda #REU_VERIFY
        jsr ri_page
        beq ri_vbad
        clc
        rts
ri_vbad:
        sec
        rts
;;; A = the command, for RI_P and REU $000000; then A = the verify error
;;; bit (Z set: none) -- the status read before too, which clears it
ri_page:
        tax
        jsr rc_status
        lda #$00
        sta rc_c64
        sta rc_ra
        sta rc_ra+1
        sta rc_ra+2
        sta rc_ln
        lda #>RI_P
        sta rc_c64+1
        lda #$01
        sta rc_ln+1
        jsr rc_dma
        jsr rc_status
        and #REU_VFAIL
        rts
;;; A to REU $0000xx, Y = xx
ri_poke:
        sta rc_fl
        sty rc_ra
        lda #<rc_fl
        sta rc_c64
        lda #>rc_fl
        sta rc_c64+1
        lda #$00
        sta rc_ra+1
        ldx #REU_STASH
        jmp rc_set1             ; (bank 0, one byte)

ri_check:
        jsr ri_verify
        bcc ri_parts
        lda #$01                ;    (else the read cache alone)
        sta rc_on
        jmp $03fc
;;; 5. the on-demand code is parts A and B now: the resident fetches A, and
;;;    no half holds the plain u6bulk any more
ri_parts:
        ldx #6
-       lda ri_bulkfl,x
        sta u6_bulkfl,x
        dex
        bpl -
        stx u6_keep             ; (X = $FF: no half)
        lda #$01
        sta rc_on
        jmp $03fc
;;; part A's flash addresses, as u6_bulkfl has u6bulk's (build.py)
ri_bulkfl:
        !byte RI_FL_DC >> 16, (RI_FL_DC >> 8) & $ff, RI_FL_DC & $ff, $ff
        !byte RI_FL_D8 >> 16, (RI_FL_D8 >> 8) & $ff, RI_FL_D8 & $ff
reu_init_end:
!if RC_PAGES > WC_COUNTS {
        !error "u6reu.s: the read cache's flags run into the write cache's counts"
}
