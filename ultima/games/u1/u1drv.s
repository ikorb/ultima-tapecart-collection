;;; u1drv.s -- Ultima 1 disk driver replacement.
;;;
;;; Overlays the original driver image at $C000.  Only two regions are
;;; replaced; everything else in the image is left byte-for-byte alone:
;;;
;;;   $C000-$C47F   was the fastloader (drive-code uploader, the $DD00
;;;                 transfer loops, the $0330 ILOAD hook) -- 1152 bytes of
;;;                 dead weight once the drive is gone.  Now tclib + adapter
;;;                 + the unit table.
;;;   $C480-$C490   the four public entry points.  These addresses are fixed:
;;;                 13 call sites across HELLO/LO/GE/TW/CA/OU reference them.
;;;
;;; Deliberately preserved and reused:
;;;   $C4FD-$C52B   the original OU cache memcpy ($E000 -> $8C9E)
;;;   $C4F8         the "save next" counter the game maintains
;;;   $C5E3-$C5FA   the save start/end tables (build.py reads them back)
;;;
;;; Reused for the options: $C52C-$C5E2, the original's dead KERNAL load
;;; routine and its name/address tables.  The options' table and the
;;; launcher's X are a segment of their own at $CE01 (the end of this file).

TCLIB_ORG    = $c000
TC_NO_CMDMODE = 1               ; the launcher already entered it; it persists
TC_INIT_ELSEWHERE = 1           ; tc_init is the init stub's (it runs once):
                                ; its ~80 bytes here are the journal's

U1_FAST      = 0                ; 1 = READ_FLASH_FAST + blank, 0 = tc_read
TC_NO_FAST    = 1               ; no blanking: TC_GUARD's tc_read is 2-bit
TC_GUARD      = 1               ; with the screen on (1-bit if a sprite is)
;;; No TC_NMI_HOLD: its ~70 bytes are not there before the entry table
;;; (5 left), and no hole elsewhere takes them.  A RESTORE during a transfer
;;; goes through the RAM's vector at $FFFA, as it always has here.

!source "tclib.s"
!source "journal.s"             ; JOURNAL from build.py (regions.journal)

;;; ==================================================================
;;; Unit table: 22 entries of 8 bytes, indexed by the game's own file index.
;;; build.py fills this in once the flash layout is known.
;;;
;;;   +0/+1  flash offset bits 8-23 (units are page aligned, low byte is 0)
;;;   +2/+3  length
;;;   +4/+5  C64 address
;;;   +6     flags
;;;   +7     spare
;;;
;;; A zero length means "not on the disk": PL (absent) and PR (on the
;;; deliberately unformatted track 6).  Both return C set, as the original
;;; driver does -- and for PR that is load bearing, because the game ignores
;;; the result and keeps the table already sitting at $12C0.
;;; ==================================================================
U1_ENTRIES   = 22
U1_SAVE_BASE = 16               ; indices 16-21 are the writable slots
F_COMPRESSED = %00000001        ; stored zx02-crunched
F_SAVESLOT   = %00000010

u1_table:
        !fill U1_ENTRIES * 8, 0

;;; ==================================================================
;;; Save slots live one per 4 KiB erase block, so writing one never disturbs
;;; another and no read-modify-write is needed.  Layout within a block:
;;;
;;;   +$000  header: $A5 $5A, then the length word
;;;   +$100  the data itself
;;;
;;; The header is written *last*, so losing power mid-save leaves the slot
;;; reading as empty rather than as a corrupt save.
;;; ==================================================================
SAVE_MAGIC0 = $a5
SAVE_MAGIC1 = $5a

;;; ==================================================================
;;; load file by index X.  C clear = loaded, C set = not present.
;;; ==================================================================
u1_load:
        cpx #U1_ENTRIES
        bcs u1_err
        txa
        asl
        asl
        asl                     ; 8 bytes per entry
        tax

        lda u1_table+6,x
        and #F_SAVESLOT
        beq +
        jmp u1_load_slot        ; (behind the entry table, for room)
+

        lda #$00
        sta tc_addr             ; page aligned
        lda u1_table+0,x
        sta tc_addr+1
        lda u1_table+1,x
        sta tc_addr+2
        lda u1_table+2,x
        sta tc_len
        lda u1_table+3,x
        sta tc_len+1
        ora tc_len
        beq u1_err              ; length 0 -> absent
        lda u1_table+4,x
        sta tc_dest
        lda u1_table+5,x
        sta tc_dest+1

        lda u1_table+6,x
        and #F_COMPRESSED
        beq +
        jsr u1_unpack           ; tc_len is the *compressed* length
        jmp u1_done
+       jsr u1_xfer
        jmp u1_done

u1_err:
        sec
        rts

;;; ------------------------------------------------------------------
;;; load a save slot: check the header, then pull the data out.
;;; X = table offset.
;;; ------------------------------------------------------------------
;;; tc_addr = the slot's block base, then read the header into u1_hdr
u1_slot_hdr:
        jsr u1_slot_base
        jsr u1_hdr_io
        jmp tc_read

u1_hdr_io:                      ; tc_len/tc_dest <- the 4-byte header
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<u1_hdr
        sta tc_dest
        lda #>u1_hdr
        sta tc_dest+1
        rts

;;; X = table offset -> tc_addr = block base
u1_slot_base:
        lda #$00
        sta tc_addr
        lda u1_table+0,x
        sta tc_addr+1
        lda u1_table+1,x
        sta tc_addr+2
        rts

;;; X = table offset -> tc_addr = block base + $100
u1_slot_data_addr:
        jsr u1_slot_base
        inc tc_addr+1
        bne +
        inc tc_addr+2
+       rts

;;; ==================================================================
;;; Do a bulk transfer.  The fast protocol cannot tolerate badlines, so blank
;;; the screen around it.  Touching $D011 needs I/O visible, and the game runs
;;; some stretches at $01 = $30 (all RAM, no I/O), so force I/O in rather than
;;; assuming.  Bit 5 stays set throughout: clearing it would turn the tape
;;; motor on and drop the cart out of command mode.
;;; ==================================================================
u1_xfer:
        lda $01
        sta u1_save01
        ;; HIRAM+CHAREN, never LORAM -- LORAM would bank BASIC ROM in over
        ;; $A000-$BFFF, which is harmless for this driver at $C000 but masks
        ;; the tail of the overlay slot, and is fatal for U3's driver at $BC00
        ora #%00000110
        sta $01
!if U1_FAST = 1 {
        jsr tc_blank            ; and wait a frame -- see tclib
        jsr tc_read_fast
        jsr tc_unblank
} else {
        jsr tc_read
}
        lda u1_save01
        sta $01
        rts

;;; The crunched path needs no blanking -- TC_GUARD's reads keep time with
;;; the screen on -- so a compressed load is also a load without the flicker.
;;; $01 still has to have I/O in for nothing here, but the decoder lives at
;;; $C600 and the destination can be anywhere, so keep the same discipline.
u1_unpack:
        lda $01
        sta u1_save01
        ora #%00000110
        sta $01
        jsr zxd_unpack
        lda u1_save01
        sta $01
        rts

;;; ==================================================================
;;; save by save-index X (0-5, i.e. file index 16+X -- the game indexes the
;;; save tables at $C5B7/$C5E3/$C5EF, not the load tables).
;;; C clear = written.
;;; ==================================================================
u1_save:
        cpx #U1_ENTRIES - U1_SAVE_BASE
        bcs u1_serr
        txa
        clc
        adc #U1_SAVE_BASE
        asl
        asl
        asl
        tax
        stx u1_ent

        lda u1_table+6,x
        and #F_SAVESLOT
        bne +
u1_serr:                        ; u1_err is out of branch range from here
        sec
        rts
+
        ;; through the journal (asm/journal.s): the slot written there first,
        ;; then in place.  The body finds the slot in its table entry, so the
        ;; entry is pointed at the journal for the first write.
        jsr u1_slot_base
        jsr jr_begin
        jsr u1_sv_tab
        jsr u1_sv_body
        jsr jr_commit
        jsr u1_sv_tab
        jsr u1_sv_body
        jsr jr_end
        clc
        rts

u1_sv_body:
        ;; erase this slot's block.  Nothing else lives in it, so there is
        ;; no other content to preserve.
        ldx u1_ent
        jsr u1_slot_base
        jsr tc_erase_block

        ;; write the data one page in
        ldx u1_ent
        jsr u1_slot_data_addr
        ldx u1_ent
        lda u1_table+2,x
        sta tc_len
        sta u1_hdr+2
        lda u1_table+3,x
        sta tc_len+1
        sta u1_hdr+3
        lda u1_table+4,x
        sta tc_dest             ; tc_write reads from tc_dest
        lda u1_table+5,x
        sta tc_dest+1
        jsr tc_write

        ;; header last: this is what makes the slot count as valid
        lda #SAVE_MAGIC0
        sta u1_hdr+0
        lda #SAVE_MAGIC1
        sta u1_hdr+1
        ldx u1_ent
        jsr u1_slot_base
        jsr u1_hdr_io
        jmp tc_write

u1_save01:  !byte 0
u1_ent:     !byte 0
u1_hdr:     !byte 0,0,0,0

;;; ==================================================================
;;; public entry points -- these addresses are load bearing
;;; ==================================================================
u1_pre_end:
!if u1_pre_end > $c480 {
        !error "the u1 driver runs into its entry table at $C480 by ", u1_pre_end - $c480
}
        * = $c480
        jmp u1_load_ou          ; $C480 load, with the OU special case
        jmp u1_save             ; $C483 save by index
        jmp u1_load             ; $C486 plain load by index
                                ; $C489 "save next": index = $C4F8 + 2
        ldx $c4f8
        inx
        inx
        jmp u1_save

;;; index 5 (OU) is never read from disk during play: LO caches it at $E000
;;; and this copies it down into the overlay slot.  Reuse the original code.
u1_load_ou:
        cpx #$05
        beq +                   ; u1_load is out of branch range from here
        jmp u1_load
+       jmp $c4fd               ; original memcpy, ends with CLC/RTS

;;; a save slot's load; it sits here because the space before the entry
;;; table ran out when the LED commands made tclib longer
u1_load_slot:
        stx u1_ent
        jsr u1_slot_hdr         ; read the 4-byte header
        lda u1_hdr+0
        cmp #SAVE_MAGIC0
        bne u1_ls_err           ; erased or half-written: no save here
        lda u1_hdr+1
        cmp #SAVE_MAGIC1
        bne u1_ls_err

        ldx u1_ent
        jsr u1_slot_data_addr   ; tc_addr = block + $100
        lda u1_hdr+2            ; trust the stored length, not the table
        sta tc_len
        lda u1_hdr+3
        sta tc_len+1
        ldx u1_ent
        lda u1_table+4,x
        sta tc_dest
        lda u1_table+5,x
        sta tc_dest+1
        jsr tc_read             ; slots are small; not worth blanking for
        clc
        rts
u1_ls_err:
        sec
        rts

;;; A unit is in: the launcher's options (asm/patch.s, at $C52C below).
;;; OU is loaded once, by LO, into its cache at $E000, under the KERNAL --
;;; so the patches look at RAM there, whatever the caller's banking.  C
;;; clear, as u1_load's.
u1_done:
        php
        sei
        lda $01
        pha
        and #%11111000
        ora #%00000101          ; all RAM but I/O; the motor bit is kept
        sta $01
        jsr pt_apply
        pla
        sta $01
        plp
        clc
        rts
pt_opts: !byte 0                ; the launcher pokes it: patches.py's bits
pa_on:   !byte 0
pa_n:    !byte 0
pa_x:    !byte 0

u1_drv_end:
!if u1_drv_end > $c4fd {
        !error "the u1 overlay reaches $C4FD, the original OU memcpy"
}

;;; ==================================================================
;;; The options' applier and table go over the original driver's KERNAL
;;; LOAD routine and its name and address tables, $C52C-$C5E2: dead since
;;; the entry table points here, and read only by build.py.  (The OU copy
;;; before it, $C4FD-$C52B, and the save tables after, $C5E3-$C5FA, stay;
;;; $C4F8 is the game's current-character variable.)
        * = $c52c
!source "patch.s"               ; (its table, PT_TAB, is at $CE01 on)

u1_sv_tab:                     ; the entry's slot <- tc_addr
        ldx u1_ent
        lda tc_addr+1
        sta u1_table+0,x
        lda tc_addr+2
        sta u1_table+1,x
        rts
u1_opt_end:
!if u1_opt_end > $c5e3 {
        !error "the u1 options run into the save tables at $C5E3 by ", u1_opt_end - $c5e3
}

;;; ==================================================================
;;; The decoder goes in the old fastloader's receive buffer, $C600-$C6FF:
;;; nothing but that loader ever used it (every absolute reference in the
;;; game's units to it is misaligned data).  NOT $CB00-$CDFF, which a
;;; watchpoint through the intro and the overworld sees untouched: it is the
;;; current settlement's map, which TW and CA copy there as they start
;;; (TW $8CF5); tests/test_u1_build.py guards it.
;;; acme emits one blob from $C000 with the holes zero filled; build.py
;;; slices it and asserts the holes are empty.
        * = $c600
!source "zxdecr.s"

u1_zx_end:
!if u1_zx_end > $c700 {
        !error "u1 decoder overruns the world map at $C700 by ", u1_zx_end - $c700
}

;;; ==================================================================
;;; $CE01-$CFFF: the launcher's X (F7 and B, u1powers.s) and the options'
;;; table, a boot segment of their own.  No unit names an address there
;;; (a static scan of every unit), the original never put anything there,
;;; and nothing loads there; $CE00 is the NMI's RTI (init_u1.s).
        * = $ce01
!source "u1powers.s"
!source "u1idle.s"
!source "u1_patches.s"          ; generated by build.py: PT_TAB

u1_ext_end:
!if u1_ext_end > $d000 {
        !error "the u1 segment at $CE01 runs into $D000 (the world's data) by ", u1_ext_end - $d000
}
