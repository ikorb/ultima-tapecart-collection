;;; u5drv.s -- Ultima 5 disk driver replacement.
;;;
;;; Every disk access in Ultima 5 goes through a 17-entry jump table at $6C00
;;; in temp.subs (which despite the name is permanently resident).  Only 7 of
;;; the 17 slots touch the drive; the other 10 are engine services -- bitmap
;;; blitting, party status, object display -- and must be left alone.
;;;
;;;   $6C00  raw block read     A = buffer page, X = sector, Y = track
;;;   $6C09  ensure disk N      A = N (1..8)
;;;   $6C1B  save-slot handling (calls $6C2D; left alone)
;;;   $6C24  LOAD by name       X = post-action, name inline after the JSR
;;;   $6C2A  check disk ID      A = $40 + N
;;;   $6C2D  disk command / SAVE, name inline
;;;   $6C30  read a 512-byte record
;;;
;;; build.py repoints the four this file implements; ~350 call sites across
;;; the overlays need no changes at all.
;;;
;;; WHERE THIS LIVES.  The resident part goes to $7700-$7AFF, the
;;; fastloader's drive-code uploader and 2-bit transfer loop, which never
;;; runs: dconfig = 2 tells the game to use plain KERNAL I/O and xyzzy then
;;; skips the install.  $7B00-$7B56 is NOT free -- it is the sound-effect
;;; routine, byte-identical in the C64 and C128 builds and called from
;;; elsewhere -- so the overlay stops at $7AFF.  That is 1024 bytes, and the
;;; driver needs more, so the rest goes into three holes in temp.subs: the
;;; original load, save and block-read routines, whose only entries were the
;;; jump-table slots this driver takes over.  See "THE HOLES" below.
;;;
;;; Nothing above $7B57 is free.  That is not the tail of u5siz.o (the file
;;; ends at $7B56); it is the game's scratch area.  main.twn at $9B13 stamps
;;; $FF into $7D00,X for X = $70 down to $00 -- eight empty-slot records,
;;; sixteen bytes apart -- and an earlier version of this driver spanned
;;; $7B58-$7DA6, so those eight stores landed inside it: one turned
;;; "STA $7750" into "STA $FF50" and the rest punched holes in the tables.
;;; Every raw sector read after that quietly did nothing, so walking out of
;;; the starting hut redrew the hut.  The RAM under I/O is no refuge either:
;;; a copy placed at $D000 was overwritten during the intro.
;;;
;;; NAMES, NOT BLOCKS -- AND THE CART DOES THE LOOKUP.  U5 addresses files by
;;; name, so the driver needs a name -> flash map for 236 files across eight
;;; disks.  None of it is in C64 memory: the tapecart's own DIR_SETPARAMS
;;; ($40) and DIR_LOOKUP ($41) hold the directory in flash and match a
;;; fixed-length name against it, returning the data bytes.  That costs about
;;; 20 bytes over the wire per load and saves both the 680-byte table buffer
;;; and the matcher -- which matters here, where the driver has 1 KiB.
;;;
;;; The name field is 13 bytes: the disk number, then the name padded to 12.
;;; Keying on (disk, name) is free that way, and it has to be keyed on the
;;; pair -- `m` and `startup` are entirely different programs depending on
;;; which disk is current.
;;;
;;; DIR_LOOKUP matches binary, with no wildcards, and the inline strings are
;;; full of them (`D*`, `G*`, `CM*`, `ST*`).  They need none: the directories
;;; on the original disks are fixed, so what `D*` resolves to is a build-time
;;; fact.  build.py emits an extra directory entry keyed by the pattern
;;; itself, pointing at the file CBM DOS would have found first.
;;;
;;; MOTOR.  U5 is the one game that is not motor-safe out of the box: it runs
;;; at $01 = $00 and banks in with $01 = $06, both of which clear bit 5 and
;;; would start the tape motor, dropping the cart back to streaming mode.
;;; build.py rewrites those two immediate operands (and four more in the boot
;;; files) to $20 and $26.

TC_NO_CMDMODE = 1               ; the menu entered it; command mode persists
TC_NO_FAST    = 1               ; everything streams at 1 bit: no 2-bit read,
                                ; no blanking -- which is what makes room for
                                ; the decoder (and a load does not blank the
                                ; screen)
ZX_ZP         = $fb             ; the decoder's two pointers, saved and restored

HOLE_A        = $6c49           ; dead routines inside temp.subs, see below
HOLE_B        = $6eae
HOLE_C        = $6de0
HOLE_D        = $6caa           ; check ID + ensure disk + their prompts

DIR_NAMELEN = 13                ; disk number + 12 name bytes
DIR_DATALEN = 8                 ; flash address (3), length (2), load address
                                ; (2), flags -- the first seven land straight in
                                ; tc_addr..tc_dest, which tclib keeps contiguous

F_WRITE     = %00000001         ; this file has a save slot
F_ZX        = %00000010         ; stored as a zx02 stream; the length is the
                                ; stream's, the file ends itself

;;; A save slot is one 4 KiB erase block: a header page, then the data.  The
;;; length has to live there rather than in the directory because the game
;;; does not always write back what it read -- it saves ROSTER as 1024 bytes
;;; where the shipped file is 1025.  The header is written last, so an
;;; interrupted save leaves the slot reading as absent rather than as a file
;;; of the wrong length.
SAVE_MAGIC0 = $a5
SAVE_MAGIC1 = $5a

        * = $7700
!ifdef U5_C128 {
;;; C128 mode (c128.inc): $7700-$7717 are subs.128's entries -- the overlay
;;; cache and the music, which the game calls there directly -- plus the
;;; music setup.  Each goes to bank 1 through C_FAR, which tells them apart
;;; by the return address this JSR pushes.  The launcher calls tc_init and
;;; u5_dirinit by their own addresses.
!source "c128.inc"
!for i, 1, SLOTS {
        jsr C_FAR
}
} else {
;;; No entries: tc_init and the directory setup (u5_dirinit in the C128
;;; build) are the init stub's own (TC_INIT_ELSEWHERE, asm/tcinit.s,
;;; asm/init_u5.s): they run once, and their room here is the journal's.
;;; (xyzzy's fastloader install, the original's JSR $7700, is never reached:
;;; dconfig is 2.)
TC_INIT_ELSEWHERE = 1
}

!ifdef U5_C128 {
;;; C128 mode: reads 2-bit with the screen on, from bank 1 (sub128.s
;;; b1_pick, b1_get) through common RAM (c128fast.s) -- no room here.  The
;;; pick decides, so tclib's fetches go there for good.
TC_PICK      = 1
TC_FETCH     = C_GET
tc_host_pick = C_PICK
}
!ifndef U5_C128 {
;;; With an Action Replay's music (armusic.s), reads are 2-bit with the
;;; screen on.  Only a C64 build, and only when the AR is there: the receive
;;; (tcguard.s, TC_GUARD's, with fixed port values) is in the AR's RAM,
;;; reached from its jump table at $8000 through the trampolines in hole D,
;;; because this driver has 64 bytes left in all and it needs ~150.  $C8
;;; bit 6 says an AR's music is there (armusic.s arinit sets it; the C128's
;;; music setup does too, but that is the other build).  tc_host_pick asks
;;; the AR's ar_pick, which looks at $D015 -- sprite DMA it cannot dodge --
;;; and points tclib's fetch at u5_arget or back at tc_getbyte.
TC_PICK     = 1
AR_ON       = $20               ; armusic.s's: the RAM at ROML and $DF00
AR_OFF      = $0a
AR_J_GET    = $8000 + 9 * 3     ; armusic.s's jump table, after the player's
AR_J_PICK   = $8000 + 10 * 3    ; entries and its own (build.py checks)
}

TCLIB_ORG = *
!source "tclib.s"

;;; ==================================================================
;;; $6C09 -- ensure disk N is "inserted".  A = 1..8.
;;;
;;; The original prompted and spun until the right BAM ID showed up.  Every
;;; disk is in flash, so this just switches which name table is live.
;;; ==================================================================
;;; $6C2A -- check disk ID.  A = $40 + N, as $6D47 computes it; falls
;;; through into $6C09's routine.
;;;
;;; A = $30 is "an Ultima IV disk" -- their BAM IDs are "01".."04" -- and only
;;; `transfer` asks for one: it then wants the BAM's name to read "U4 DISK C"
;;; (the save disk, Britannia) in the sector buffer at $7F00, where the
;;; original's check left the BAM, and reads track 14 sectors 0-1, U4's
;;; party, through $6C00.  Ultima IV is on the cart too, so those two blocks
;;; are its save slots: the U4 disk becomes disk 1's table entry, whose own
;;; disk (the Program disk) has no raw-sector area, and build.py points that
;;; entry's run at U4's slots from block 273 (track 14 sector 0) up.
u5_checkid:
        cmp #$30
        beq u5_u4disk
        sec
        sbc #$40
u5_setdisk:
        sta u5_disk             ; the cart keys on it; nothing to reload
        clc                     ; C clear = the right disk is in.  $6D47 and
        rts                     ; $6CAA both signal a mismatch with C set, and
                                ; callers prompt and retry forever on one --
                                ; the sbc above leaves it set, so this matters
u5_u4disk:
        lda #$55                ; "U4 DISK C": the three bytes transfer tests
        sta $7f90
        lda #$34
        sta $7f91
        lda #$43
        sta $7f98
        lda #$01                ; disk 1's table entry, see above
        bne u5_setdisk

;;; ==================================================================
;;; $6C24 -- LOAD the file named inline after the JSR.
;;;
;;;   ldx #$00 / jsr $6C24 / !byte "NAME",0
;;;     X = 0  return to the byte after the string
;;;     X = 1  JMP $8000   (mode root)
;;;     X = 2  JMP $A700   (overlay)
;;; ==================================================================
u5_load:
        stx u5_post
        jsr u5_enter           ; balanced: the JSR's own return address is
                                ; gone again before the PLAs below
!ifndef U5_C128 {
        jsr $0126               ; the music quiet while the cart holds the
}                               ; machine (an RTS without an Action Replay:
                                ; armusic.s; the C128's u5_enter does it)
        pla                     ; the return address points one before the
        sta u5_pat+1            ; inline string
        pla
        sta u5_pat+2
        inc u5_pat+1
        bne +
        inc u5_pat+2
+
        ;; measure the name and find the continuation address
        ldy #$00
u5_ln_scan:
        jsr u5_patb
        beq u5_ln_end
        iny
        bne u5_ln_scan
u5_ln_end:
        sty u5_plen
        iny                     ; step past the NUL
        clc
        tya
        adc u5_pat+1
        sta u5_cont
        lda u5_pat+2
        adc #$00
        sta u5_cont+1

        lda #$00
        sta u5_ok
        jsr u5_lookup
        bcs u5_ld_done          ; unknown name: leave memory alone
        lda u5_flags
        and #F_WRITE
        beq +
        jsr u5_slotread         ; a save slot: the length is in its header
        bcs u5_ld_done
+       jsr u5_fetch
        jsr pt_apply            ; the launcher's options (asm/patch.s)
        inc u5_ok

u5_ld_done:
!ifndef U5_C128 {
        jsr $0129               ; and on again
}
        jsr u5_exit        ; before the post-action: two of the three
                                ; exits are a JMP into the loaded program
        lda u5_post
        beq u5_ld_return
        cmp #$01
        beq u5_ld_8000
        jmp $a700
u5_ld_8000:
        jmp $8000

;;; Callers test the carry: $8A14 in `startup` is
;;;     ldx #$00 / jsr $6C24 / "HTXT",0 / bcs -6
;;; so returning with it set -- which the subtraction below leaves it -- is an
;;; infinite reload rather than an error.  The original returned C clear from
;;; the KERNAL CLOSE on success and looped internally on failure; here a name
;;; that is not in the table returns C set and the caller decides.
u5_ld_return:
        lda u5_cont             ; push (continuation - 1); RTS adds it back
        sec
        sbc #$01
        tax
        lda u5_cont+1
        sbc #$00
        pha
        txa
        pha
        lda u5_ok
        beq u5_ld_bad
        clc
        rts
u5_ld_bad:
        sec
        rts

;;; ==================================================================
;;; Ask the cart to look the name up.  C clear and tc_addr/tc_len/tc_dest
;;; set if it was found.
;;;
;;; tc_sendbyte and tc_getbyte both preserve Y, which is what lets the name
;;; be streamed straight out of the caller's code as it is measured.
;;; ==================================================================
u5_lookup:
        jsr tc_enter
        lda #CMD_DIR_LOOKUP
        jsr tc_sendbyte
        lda u5_disk
        jsr tc_sendbyte
        ldy #$00
u5_lk_byte:
        cpy u5_plen
        bcs u5_lk_pad           ; past the name: pad to the fixed length
        jsr u5_patb
        jmp u5_lk_send
u5_lk_pad:
        lda #$00
u5_lk_send:
        jsr tc_sendbyte
        iny
        cpy #DIR_NAMELEN-1
        bne u5_lk_byte

        jsr tc_getbyte
        bne u5_lk_miss          ; non-zero "found" marker
        ;; flash address (3), length (2), destination (2) -- the destination
        ;; is the file's own PRG header, honoured because U5 loads with SA=1.
        ;; tclib keeps tc_addr..tc_dest+1 contiguous, so one loop fills all
        ;; seven.
        ldy #$00
-       jsr tc_getbyte
        sta tc_addr,y
        iny
        cpy #$07
        bne -
        jsr tc_getbyte
        sta u5_flags
        jsr tc_leave
        clc
        rts
u5_lk_miss:
        jsr tc_leave
        sec
        rts

u5_patb:                        ; A <- byte Y of the caller's inline pattern
u5_pat: lda $ffff,y
        rts

;;; ==================================================================
;;; Fetch the unit at tc_addr into tc_dest: decode a zx02 stream of tc_len
;;; bytes, or copy tc_len raw bytes, as u5_flags says.  Both at 1 bit, with
;;; the transfer in all-RAM banking (tc_enter), so a unit can land under I/O
;;; or ROM; the display is never blanked.
;;; ==================================================================
u5_fetch:
        lda u5_flags
        and #F_ZX
        beq u5_raw
        lda tc_dest
        sta zx_dst
        lda tc_dest+1
        sta zx_dst+1
        jsr tc_stream_open
        jsr zx_unpack
        jmp tc_stream_close
u5_raw: jmp tc_read

;;; ==================================================================
;;; u5_enter / u5_exit -- put the caller's I flag back.
;;;
;;; tc_enter does SEI and tc_leave deliberately does not undo it
;;; -- it has no idea what the caller wants.  U5 plays with interrupts ENABLED
;;; and its keyboard comes from the KERNAL's own IRQ scan, so a driver call
;;; that returns with I still set leaves the machine deaf: the game runs, the
;;; screen updates, and no key is ever seen again.  That is what stalled
;;; character creation at the first lore screen -- confirmed on hardware,
;;; where the same screen has I clear booted from disk and set booted from the
;;; cart.  Ultima 2, 3 and 4 all carry the same wrapper.
u5_enter:
        php
        pla
        sta u5_iflag
!ifdef U5_C128 {
;;; C128 mode: the music is muted around every transfer, as the original's
;;; disk routines did ($0126, which leaves the MMU at $0E) -- the IRQ is off
;;; while the cart talks, and a voice left gated would drone -- and the
;;; transfer runs in bank 0 with all RAM, whatever the caller had: a load
;;; can land under the KERNAL or I/O, and the decoder reads back what it
;;; wrote.  (tc_enter's all-RAM $01 is the C64's banking; the C128 banks
;;; with the MMU.)  On a C64 $0126/$0129 are RTS stubs (xyzzy).
        lda $ff00
        sta u5_mmu
        jsr $0126
        lda #MMU_B0
        sta $ff00
}
        rts

;;; Clobbers A and the flags, so call it before setting up a return value.
;;; (C128: X and Y too -- $0129 re-arms the music's timer and vectors.)
!ifndef U5_C128 {
u5_exit:
        lda u5_iflag
        and #%00000100          ; the caller's I
        bne +
        cli
+       rts
}                               ; (the C128 build's is in hole D, for room)

u5_iflag:    !byte 0
u5_bpage:    !byte 0
u5_bsec:     !byte 0
u5_btrk:     !byte 0
u5_disk:     !byte 1            ; the Program disk is "inserted" at boot
u5_post:     !byte 0
u5_plen:     !byte 0
u5_cont:     !byte 0,0
u5_ok:       !byte 0
u5_flags:    !byte 0
;;; build.py fills these in; $FFFF is a placeholder it asserts against
u5_dirpage:  !word $ffff        ; flash page of the directory
u5_dircount: !word $ffff        ; entries in it
;;; ==================================================================
;;; $6C2D -- disk command, then SAVE.  The inline block is
;;;
;;;     jsr $6C2D / !byte "S:TLIST",0 / !word start / !word length
;;;
;;; The original sent the whole name on the command channel to scratch the
;;; file, then SETNAM'd the name *plus two* -- skipping the "S:" -- and
;;; SAVEd start..start+length.  Here the scratch is meaningless and the save
;;; goes to the file's slot.
;;; ==================================================================
;;; The stack work is resident -- the return address it pulls and the
;;; continuation it pushes belong to the caller -- and the rest lives in one
;;; of the holes in temp.subs.
u5_save:
        pla                     ; the return address points one before the
        sta u5_pat+1            ; inline block
        pla
        sta u5_pat+2
        inc u5_pat+1
        bne +
        inc u5_pat+2
+       jsr u5_enter
!ifndef U5_C128 {
        jsr $0126
}
        jsr u5_savefar
!ifndef U5_C128 {
        jsr $0129
}
        jsr u5_exit
        lda #$01                ; a save always "succeeds": C clear on return
        sta u5_ok
        jmp u5_ld_return        ; push the continuation, as a load does

;;; ==================================================================
;;; $6C00 -- raw block read.  A = buffer page, X = sector, Y = track.
;;;
;;; Every disk carries a private data area that is in no file: blocks marked
;;; allocated in the BAM but belonging to no directory entry, on tracks 19-35
;;; (2A, 2B), 24-35 (3A, 3B, 4A, 4B) and 23-35 (1B).  That is what main.twn,
;;; main.out, main.dng and t read through here, with the track and sector
;;; computed from game state -- 27 call sites, not the "handful of direct
;;; sector reads" the notes describe.
;;;
;;; Each disk's area is stored as one contiguous run in linear block order,
;;; so the mapping is arithmetic and needs no directory lookup: a town map is
;;; four of these reads and a 16 ms lookup each would be felt.  Storing the
;;; whole span rather than just the orphan blocks costs 42 KiB and makes the
;;; mapping two numbers per disk.
;;;
;;; $6C30 (512-byte record) needs no separate replacement: $6E7B converts a
;;; record number to a track and sector and calls $6EAE twice, and build.py
;;; points those two calls here.
;;;
;;; Resident, all of it: this is the path a town map takes four times over.
;;; ==================================================================
u5_block:
        sta u5_bpage
        stx u5_bsec
        sty u5_btrk
        jsr u5_enter

        ;; linear block = sector + the sectors on every track before this
        ;; one: 21 on 1-17, 19 on 18-24, 18 on 25-30, 17 on 31-35.  Summed
        ;; rather than tabulated -- the table was 70 bytes the driver could
        ;; not spare, and 34 passes of this loop are ~900 cycles against a
        ;; 30 ms transfer.
        lda u5_bsec
        sta u5_blk
        lda #$00
        sta u5_blk+1
        ldx #$01
u5_lin:
        cpx u5_btrk
        beq u5_lin_done
        lda #21
        cpx #18
        bcc u5_lin_add
        lda #19
        cpx #25
        bcc u5_lin_add
        lda #18
        cpx #31
        bcc u5_lin_add
        lda #17
u5_lin_add:
        clc
        adc u5_blk
        sta u5_blk
        bcc +
        inc u5_blk+1
+       inx
        bne u5_lin
u5_lin_done:

        ldx u5_disk             ; index the per-disk tables
        dex
        sec                     ; offset = block - first
        lda u5_blk
        sbc u5_rfirst_lo,x
        sta u5_off
        lda u5_blk+1
        sbc u5_rfirst_hi,x
        sta u5_off+1
        bcc u5_blk_out          ; below the stored run -- or no run at all:
                                ; build.py gives those disks first = $FFFF.
                                ; There is no upper bound to check, because
                                ; every run extends to the last block.

        ;; The block's entry in its disk's block map: four bytes, the 24-bit
        ;; flash address of its zx02 stream and the stream's length, 0 for a
        ;; page stored raw.
        asl u5_off
        rol u5_off+1
        asl u5_off
        rol u5_off+1
        clc
        lda u5_rmap_lo,x
        adc u5_off
        sta tc_addr
        lda u5_rmap_mid,x
        adc u5_off+1
        sta tc_addr+1
        lda u5_rmap_hi,x
        adc #$00
        sta tc_addr+2
        jsr u5_hdrsetup         ; four bytes into u5_hdr
        jsr tc_read
        ldy #$02
-       lda u5_hdr,y
        sta tc_addr,y
        dey
        bpl -
        lda #$00
        sta tc_dest
        sta tc_len+1
        ldx #F_ZX
        lda u5_hdr+3
        sta tc_len
        bne +
        inc tc_len+1            ; raw: one whole page
        ldx #$00
+       stx u5_flags
        lda u5_bpage
        sta tc_dest+1
        jsr u5_fetch
u5_blk_fetched:                 ; (a label for the test harness only)
        pha                     ; keep whatever the caller may test
        jsr u5_exit
        pla
        clc                     ; C clear = read: transfer ($81F4), main.out,
        rts                     ; p, startup, dng.precom and main.dng's $6C30
                                ; retry or give up on C set, and the fetch
                                ; leaves C as it ends -- set after a raw page
                                ; (tc_getbyte's stop bit), clear after zx02

u5_blk_out:
        jmp u5_exit             ; outside the stored run: leave the buffer be

!ifndef U5_C128 {
;;; TC_PICK: A = the read command.  1-bit unless an AR is there, when its
;;; ar_pick decides (it keeps A's command unless the reads go through it).
tc_host_pick:
        lda #CMD_READ_FLASH
        bit $c8                 ; bit 6: an AR's music
        bvc +
        jsr u5_armap
        jsr AR_J_PICK
        jmp u5_arout
+       rts

;;; a save through the journal (asm/journal.s): the slot written there first,
;;; then in place.  u5_write takes the slot from tc_addr.
u5_jwrite:
        jsr jr_begin
        jsr u5_write
        jsr jr_commit
        jsr u5_write
        jmp jr_end
!set JR_PART = 1
!source "journal.s"             ; JOURNAL from build.py (regions.journal);
}                               ; the rest is in hole C

u5_drv_end:
!if u5_drv_end > $7b00 {
        !error "the u5 driver reaches $7B00, the sound-effect routine: ", u5_drv_end - $7b00, " bytes over"
}

;;; ==================================================================
;;; THE HOLES.  Three routines inside temp.subs are the original disk code
;;; whose jump-table entries this driver has taken over, so nothing reaches
;;; them any more:
;;;
;;;   $6C49-$6CA9   LOAD by name     ($6C24 was its only entry)
;;;   $6DE0-$6E7A   scratch + SAVE   ($6C2D)
;;;   $6EAE-$6F4C   raw block read   ($6C00, and the two calls in $6E7B
;;;                                   that build.py repoints)
;;;   $6CAA-$6DDF   check disk ID    ($6C2A), ensure disk ($6C09) and the
;;;                 "insert ... disk" prompt with the seven disk names, which
;;;                 only those two reach.  Added for the zx02 decoder: no RAM
;;;                 access in a memmap of 120 steps of play with a fight, and
;;;                 the only references from other files are misaligned bytes
;;;                 (MAIN.COMBAT's "JMP $6CF0" is the operand of JSR $4C3F /
;;;                 BEQ) and map, text and talk data.
;;;
;;; Checked both ways.  VICE's memmap shows no RAM access to any of it from
;;; boot through the intro, Journey Onward, the town, the exit and the
;;; overworld.  And every absolute JSR/JMP/LDA/STA into those ranges across
;;; all 236 files comes from inside the dead routines themselves, or turns
;;; out to be misaligned bytes (`jsr $4C1B / sec / ror ...` reads as a "JMP
;;; $6E38") or text.  What is next to them stays: the second jump table at
;;; $6C34-$6C48, the device byte at $6C33, the record routine at
;;; $6E7B-$6EAD with its two variables, and $6F4D, which the targeting
;;; cursor at $6F4E uses as a variable.
;;;
;;; The rest of $7B57-$7FFF, where this used to live, is not free at all --
;;; see the header.  build.py writes these three pieces into temp.subs
;;; itself, so they survive anything that reloads it.
;;; ==================================================================
        * = HOLE_A

;;; Point tc_addr/tc_len at a save slot's contents.  C set if the slot has
;;; never been written -- the game then sees a load error, which for ROSTER
;;; is exactly the "No active game!" path it already has.
u5_slotread:
        lda tc_dest             ; u5_hdrsetup points tc_dest at the header
        sta u5_sd               ; buffer, so park the real destination
        lda tc_dest+1
        sta u5_sd+1
        jsr u5_hdrsetup
        jsr tc_read
        lda u5_sd
        sta tc_dest
        lda u5_sd+1
        sta tc_dest+1
        lda u5_hdr+0
        cmp #SAVE_MAGIC0
        bne u5_sr_empty
        lda u5_hdr+1
        cmp #SAVE_MAGIC1
        bne u5_sr_empty
        lda u5_hdr+2
        sta tc_len
        lda u5_hdr+3
        sta tc_len+1
        inc tc_addr+1           ; the data sits one page in
        bne +
        inc tc_addr+2
+       clc
        rts
u5_sr_empty:
        sec
        rts

;;; tc_len/tc_dest for a header transfer; tc_addr is left alone
u5_hdrsetup:
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<u5_hdr
        sta tc_dest
        lda #>u5_hdr
        sta tc_dest+1
        rts


u5_hole_a_end:
!if u5_hole_a_end > $6caa {
        !error "hole A overflows into $6CAA by ", u5_hole_a_end - $6caa, " bytes"
}

        * = HOLE_C
;;; erase the slot, write the data a page in, then the header
u5_write:
        lda tc_addr+1
        sta u5_slot
        lda tc_addr+2
        sta u5_slot+1
        jsr tc_erase_block

        inc tc_addr+1
        bne +
        inc tc_addr+2
+       lda u5_wsrc
        sta tc_dest
        lda u5_wsrc+1
        sta tc_dest+1
        lda u5_wlen
        sta tc_len
        lda u5_wlen+1
        sta tc_len+1
        jsr tc_write

        lda #SAVE_MAGIC0
        sta u5_hdr+0
        lda #SAVE_MAGIC1
        sta u5_hdr+1
        lda u5_wlen
        sta u5_hdr+2
        lda u5_wlen+1
        sta u5_hdr+3
        lda #$00
        sta tc_addr
        lda u5_slot
        sta tc_addr+1
        lda u5_slot+1
        sta tc_addr+2
        jsr u5_hdrsetup
        jmp tc_write


;;; ==================================================================
;;; Point the cart at the directory.  It keeps the parameters until they are
;;; set again, so this runs once, from the init stub.
;;; ==================================================================
!ifndef U5_C128 {
!set JR_PART = 2
!source "journal.s"             ; (its first part is in the main segment)
} else {
u5_dirinit:
        jsr tc_enter
        lda #CMD_DIR_SETPARAMS
        jsr tc_sendbyte
        lda #$00                ; the directory is page aligned
        jsr tc_sendbyte
        lda u5_dirpage
        jsr tc_sendbyte
        lda u5_dirpage+1
        jsr tc_sendbyte
        lda u5_dircount
        jsr tc_sendbyte
        lda u5_dircount+1
        jsr tc_sendbyte
        lda #DIR_NAMELEN
        jsr tc_sendbyte
        lda #DIR_DATALEN
        jsr tc_sendbyte
        jmp tc_leave
}

u5_hole_c_end:
!if u5_hole_c_end > $6e7b {
        !error "hole C overflows into the record routine by ", u5_hole_c_end - $6e7b, " bytes"
}

        * = HOLE_B
;;; ==================================================================
;;; the rest of $6C2D, in hole B: measure the name, pick the parameters out of the
;;; inline block, and write the slot
;;; ==================================================================
u5_savefar:
        ldy #$00
u5_sv_scan:
        jsr u5_patb
        beq +
        iny
        bne u5_sv_scan
+       sty u5_plen

        ;; the four parameter bytes follow the name's NUL
        ldy u5_plen
        iny
        jsr u5_patb
        sta u5_wsrc
        iny
        jsr u5_patb
        sta u5_wsrc+1
        iny
        jsr u5_patb
        sta u5_wlen
        iny
        jsr u5_patb
        sta u5_wlen+1

        ;; continuation = name + plen + 1 + 4
        lda u5_plen
        clc
        adc #$05
        clc
        adc u5_pat+1
        sta u5_cont
        lda u5_pat+2
        adc #$00
        sta u5_cont+1

        ;; look the file up under its real name, without the "S:"
        lda u5_pat+1
        clc
        adc #$02
        sta u5_pat+1
        bcc +
        inc u5_pat+2
+       dec u5_plen
        dec u5_plen
        jsr u5_lookup
        bcs u5_sv_done
        lda u5_flags
        and #F_WRITE
        beq u5_sv_done          ; read-only: drop the write rather than
                                ; corrupt the image
!ifdef U5_C128 {
        jsr u5_write            ; (C128 mode: no room for the journal)
} else {
        jsr u5_jwrite
}

u5_sv_done:
        rts




;;; build.py fills these in; $FF is a placeholder it asserts against.
;;; Split into byte tables so one index (disk - 1) reaches all of them.
u5_rfirst_lo: !fill 8, $ff      ; first linear block stored, per disk
u5_rfirst_hi: !fill 8, $ff
u5_rmap_lo:   !fill 8, $ff      ; flash address of that disk's block map
u5_rmap_mid:  !fill 8, $ff
u5_rmap_hi:   !fill 8, $ff

;;; the save and block paths' variables -- RAM like any other, just not in
;;; the 1 KiB window that had run out
u5_wsrc:     !byte 0,0
u5_wlen:     !byte 0,0
u5_slot:     !byte 0,0
u5_hdr:      !byte 0,0,0,0
u5_sd:       !byte 0,0
u5_blk:      !byte 0,0
u5_off:      !byte 0,0

u5_hole_b_end:
!if u5_hole_b_end > $6f4d {
        !error "hole B overflows into $6F4D by ", u5_hole_b_end - $6f4d, " bytes"
}

        * = HOLE_D
zx_getbyte = tc_stream_byte
!source "zx02s.s"
PT_STREAM = 1                   ; the table is in the cart: no room here
!source "patch.s"
pt_opts: !byte 0                ; the launcher pokes it: patches.py's bits
pa_on:   !byte 0
pa_n:    !byte 0
pt_where: !byte $ff, $ff, $ff, $ff, $ff ; build.py: the table's flash address, length
!ifdef U5_C128 {
;;; sub128.s loads an overlay that is not cached through here: it puts the
;;; letter in and C_B0 calls this in bank 0.  C set if the load failed.
u5_c128_ld:
        ldx #$00
        jsr $6c24
u5_c128_letter:
        !byte 0, 0
        rts

u5_exit:
        lda u5_mmu
        sta $ff00
        jsr $0129               ; unmute; keeps the MMU and the I flag
        lda u5_iflag
        and #%00000100          ; the caller's I
        bne +
        cli
+       rts
u5_mmu: !byte 0
} else {
;;; the fetch ar_pick points tclib at: one byte, 2-bit, from the AR's RAM
;;; (ROML needs LORAM and HIRAM, so $01 is $27 for the byte), then the AR
;;; off and tclib's all-RAM banking back before anything is stored.  Keeps
;;; A and Y, as tc_getbyte does.  Started from the Ultima VI EasyFlash, the
;;; two writes of the AR's register become the EasyFlash's in RAM
;;; (build.py build_efmusic, which checks these bytes: same lengths).
u5_arget:
        jsr u5_armap
        jsr AR_J_GET
u5_arout:
        ldx #AR_OFF
        stx $de00
        ldx tc_v_base
        stx $01
        rts
u5_armap:
        lda #$27                ; ROML, I/O and the KERNAL; write low
        sta $01
        lda #AR_ON
        sta $de00
        rts
}

u5_hole_d_end:
!if u5_hole_d_end > $6de0 {
        !error "hole D overflows into hole C by ", u5_hole_d_end - $6de0, " bytes"
}
