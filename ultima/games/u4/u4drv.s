;;; u4drv.s -- Ultima 4 disk driver replacement.
;;;
;;; Every floppy access in Ultima 4 funnels through ONE routine: LOADBLK at
;;; $A45E in the resident kernel ($A100-$A6FF), reached either directly
;;; (`JSR $A103`, the public jump-table entry) or from the chunk/record
;;; dispatcher's retry loop at $A1C0.  Its contract is the drive parameter
;;; block at $A000:
;;;
;;;   $A000 DK_OP    1 = read, 2 = write
;;;   $A001 DK_CNT   number of 256-byte blocks
;;;   $A002 DK_ADR   destination (or source) address, word
;;;   $A004 DK_BLK   linear block number, word, 0-based from T1/S0
;;;
;;; and it returns C=0 on success, C=1 on a read failure.
;;;
;;; So this file is simply LOADBLK rewritten to fetch from flash.  Nothing
;;; else in the kernel is patched: the jump table, the dispatcher, the
;;; chunk/record tables and the boot routine are all untouched, and the
;;; track/sector conversion at $A48F, the 1541 geometry table at $A4E4 and
;;; every KERNAL serial call from $A52F to $A673 become dead code -- which is
;;; exactly the room this driver's front half occupies.
;;;
;;; TWO PIECES:
;;;
;;;   $A45E-$A673  the resident part.  Starts at LOADBLK itself, so the seam
;;;                needs no patch at all.  Must not reach $A674: BANKOUT/
;;;                BANKIN and the IRQ/NMI trampolines live there and stay
;;;                live.  It holds the entries, the disk-swap hook and all
;;;                the launcher pokes (the map table, the options byte).
;;;   $D000-       the rest: the body, tclib (1-bit and streaming only), the
;;;                zx02 decoder, the options' patcher and the block-map
;;;                buffer, in the RAM under I/O.  Every write to
;;;                $01 on the four disks is $35 or $36 (I/O always in), so no
;;;                code of the game can reach that RAM, no chunk or record
;;;                loads there, and the VIC works in bank 0.  u4_in banks it
;;;                in ($01 = $34) for a call.  It used to be $A700-$A98B,
;;;                which is now Remastered's colour tables 1-3 (tileset.py).
;;;
;;; An NMI (RESTORE) while the rest runs would come back through the
;;; kernel's trampoline with $01 = $35, under code that is then not there;
;;; so the NMI vector points at an RTI for the length of a call.
;;;
;;; acme emits one blob spanning both with the hole zero-filled; build.py
;;; slices it and asserts the hole really is empty, which is what proves the
;;; glue never grew into $A674.
;;;
;;; WHICH DISK.  Unlike Ultima 3, U4 has a real notion of a current disk and
;;; verifies it (docs/reversing-notes/u4.md): the swap overlay loads record
;;; $00 -- one byte, block 0, to $0050 -- and compares it with the wanted
;;; disk number in $5E.  Three copies of that overlay exist on disk A and
;;; build.py points all three at u4_setdisk below, which records the wanted
;;; disk for the block router and returns as if the swap had happened.  The
;;; game's disk numbers are NOT in disk-letter order: 1=A, 2=C (Britannia),
;;; 3=B (Towne), 4=D (Underworld).

TC_NO_CMDMODE = 1               ; the menu entered it; command mode persists
TC_IRQ_ON     = 1               ; the music plays on through a load (u4_irqs)
TC_NO_FAST    = 1               ; no blanking; see u4_read
TC_GUARD      = 1               ; 2-bit reads with the screen on, sprites off
TC_GUARD_ELSEWHERE = 1          ; its I/O-banked part is resident, below
ZX_ZP         = $fb             ; the decoder's two pointers, saved and restored

;;; the kernel's drive parameter block
DK_OP       = $a000
DK_CNT      = $a001
DK_ADR      = $a002
DK_BLK      = $a004

;;; The save slots: disk 2 (Britannia), linear blocks 271-275.  Chunk $7E ->
;;; 271, $7F -> 272, $80 -> 273-274, record $1A -> 275.  Each gets its own
;;; 4 KiB erase block so a save never read-modify-writes a neighbour.
SAVE_DISK   = 2
SAVE_FIRST  = 271
SAVE_COUNT  = 5

;;; The temporary map (chunk $7E, one block: the surface's objects as they
;;; were when the party went into a town or a dungeon) is written at every
;;; such entry and read back at the exit.  On the cart that was an erase of
;;; its slot's 4 KiB and a page written, every time.  Now the write lands in
;;; a RAM copy under the I/O, the read comes from it once there is one, and
;;; the next write of chunk $7F -- every Quit & save, on the surface or (the
;;; Remastered's) in a dungeon -- puts the copy in its slot first, so a saved
;;; game holds the one it needs.  A game played and not saved loses it, as
;;; it loses the rest (the Remastered kit's cache).
TMAP        = $df00             ; the copy
TMAP_BLK    = SAVE_FIRST        ; chunk $7E's block
QUIT_BLK    = SAVE_FIRST + 1    ; chunk $7F's
SAVE_SHIFT  = 4                 ; 16 pages per erase block

;;; Block map entries fetched per flash read.  Each costs four bytes of RAM
;;; here; a batch boundary only costs one more map read, never a wrong block.
MAP_BATCH   = 16

        * = $a45e

;;; ==================================================================
;;; LOADBLK replacement.
;;;
;;; U4 plays with interrupts enabled (the sound driver runs from the IRQ),
;;; and the caller's I flag has to be put back by hand at the end.  PLP would
;;; do it but would also clobber the carry the caller is about to test.
;;; The music plays on through a load (u4_irqs: the IRQ
;;; runs during it, through u4_irq and u4_kirq) -- unless the game has an
;;; IRQ handler of its own in $0314 (character creation's raster split),
;;; when the load runs with interrupts off, as they all did before.
;;; ==================================================================
u4_transfer:
        php
        pla
        sta u4_flags
        jsr u4_irqs             ; masked, or the caller's again (after $A500)
        jsr u4_in
        jsr u4_run
        jsr pt_apply            ; the launcher's options (asm/patch.s)
        jsr u4_out
        jsr u4_irqs_out
u4_xfer_done:                   ; (a label for the test harness only)
        lda u4_flags
        and #%00000100          ; caller's I flag
        bne +
        cli
+       clc                     ; flash never fails to read
        rts

;;; the init stub's entry: tclib's init, with the rest banked in
u4_init:
        php
        sei
        jsr u4_in
        jsr tc_init
        jsr u4_out
        plp
        rts

;;; the RAM under I/O in, and the NMI vector at an RTI meanwhile; u4_out
;;; puts both back.  Interrupts are off.
;;;
;;; And no NMI at all while the cart talks: the 2-bit read (TC_GUARD) is
;;; timed, and RESTORE's NMI in the middle of a byte would corrupt it.  An
;;; NMI cannot be masked, but it is edge triggered, so CIA 2's timer A
;;; underflows once here and its interrupt is left unacknowledged: the NMI
;;; line stays low and a RESTORE pulse makes no edge.  u4_out reads $DD0D,
;;; which lets the line go.  Nothing on U4's disks touches CIA 2 but $DD00
;;; (a scan of all four for absolute $DD0x operands: one hit, graphics).
u4_in:  php
        sei
        lda $01
        sta u4_01
        lda #$35                ; I/O in, and the RAM's NMI vector
        sta $01
        lda $fffa
        sta u4_nmi
        lda $fffb
        sta u4_nmi+1
        lda #<u4_rti
        sta $fffa
        lda #>u4_rti
        sta $fffb
        lda #$01                ; timer A from 1, one shot, its NMI on
        sta $dd04
        lda #$00
        sta $dd05
        lda #$81
        sta $dd0d
        lda #$19
        sta $dd0e
-       lda $dd0e               ; until it has run out (START clears)
        lsr
        bcs -
        lda #$34
        sta $01
        plp
        rts
u4_out: php
        sei
        lda #$35
        sta $01
        lda #$01                ; timer A's NMI off, and the one taken
        sta $dd0d               ; acknowledged: the line goes high
        lda $dd0d
        lda u4_nmi
        sta $fffa
        lda u4_nmi+1
        sta $fffb
        lda u4_01
        sta $01
        plp
        rts
u4_rti: rti

;;; ==================================================================
;;; u4_setdisk -- replaces the disk-swap overlay's entry point.
;;;
;;; The original stored the wanted disk in $5E, printed "PLEASE PLACE THE
;;; <name> DISK INTO DEVICE <n> AND PRESS [F1]", waited, then read record $00
;;; back and re-prompted unless it matched.  Every disk is in flash, so all
;;; that is left is to record the number and tell the game its own cache that
;;; the disk is in drive 1.  $51 is the drive count and $51+$5F the "disk
;;; currently in drive N" cache, so this keeps callers that consult the cache
;;; before asking for a swap consistent.
;;; ==================================================================
;;; (At $A500: build.py writes JMP u4_setdisk over the overlays' STA $5E,
;;; and at two of the three its last byte lands on the body's first, LDA's
;;; $A5 -- the body is dead, but its bytes stay the original's this way, and
;;; build.py and the tests find the overlays by them.)
u4_pre_setdisk:
!if u4_pre_setdisk > $a500 {
        !error "the resident part runs past $A500, where u4_setdisk is pinned"
}
        * = $a500
u4_setdisk:
        sta $5e                 ; wanted disk, as the original entry did
        sta u4_disk
        lda #$01
        sta $5f                 ; one drive
        lda $5e
        sta $52                 ; $51 + drive 1
        rts

;;; ==================================================================
;;; Flash map.  build.py overwrites both tables; the values here are only
;;; placeholders, and the assertion in build.py is what guarantees they were
;;; replaced.  (Resident: the launcher pokes the map and the options byte.)
;;; ==================================================================
u4_map_lo:   !byte $ff, $ff, $ff, $ff   ; disk 1..4: flash address of its
u4_map_mid:  !byte $ff, $ff, $ff, $ff   ; block map, 683 entries of four
u4_map_hi:   !byte $ff, $ff, $ff, $ff   ; bytes each (see u4_read)
u4_savepage: !word $ffff                ; save region base page

u4_disk:     !byte 1            ; disk A is "inserted" at boot; the segment is
                                ; reloaded from flash every run, so this is a
                                ; genuine power-on default, not stale state
u4_flags:    !byte 0
u4_01:       !byte 0
u4_nmi:      !word 0
pt_opts:     !byte 0            ; the launcher pokes it: patches.py's bits

;;; ---- the music through a load ------------------------------------------
;;; A load may be interrupted, and three things in U4's IRQ path would
;;; break it.  The kernel's IRQ entry ($A696) left with $01 = $35 whatever
;;; it had been -- the driver runs at $34, under the I/O -- and it and $A6AC
;;; wrote $35/$36 whole, which drops the cassette write line mid-byte.  And
;;; the KERNAL's IRQ ($EA31, via $0314) has the tape motor code, which starts
;;; the motor -- the cart back in streaming mode -- when the cart is busy.
;;; So the kernel's entry comes here (build.py: $A696 JMP u4_irq) and keeps
;;; the interrupted $01, and bits 3-5 of it throughout ($A6AC keeps them
;;; too, build.py); and for a load $0314 is u4_kirq, the KERNAL's IRQ past
;;; its motor code.  The music's handler, in the kernel's vector $A116 (disk
;;; A block 307), then the KERNAL's IRQ, run as they did.

;;; A load's interrupts: if $0314 is the KERNAL's own ($EA31), on again (the
;;; caller's I flag) with $0314 at u4_kirq; else off for the load.
u4_irqs:
        sei
        lda #$00
        sta u4_kvec
        lda $0314
        cmp #$31
        bne +
        lda $0315
        cmp #$ea
        bne +
        lda #<u4_kirq
        sta $0314
        lda #>u4_kirq
        sta $0315
        inc u4_kvec
        lda u4_flags
        and #%00000100
        bne +
        cli
+       rts
u4_irqs_out:
        sei
        lda u4_kvec
        beq +
        lda #$31
        sta $0314
        lda #$ea
        sta $0315
+       rts
u4_kvec: !byte 0

;;; the kernel's IRQ entry, $A696's: as it was, but the interrupted $01 kept
;;; for the way out, and its bits 3-5 (the cassette lines) kept meanwhile
u4_irq: pha
        txa
        pha
        lda $01
        pha
        tsx
        lda $0104,x             ; the P the interrupt pushed
        tax
        lda #>u4_irq_out        ; a frame the KERNAL's RTI returns through
        pha
        lda #<u4_irq_out
        pha
        txa
        pha
        lda $01
        and #%00111000
        ora #%00000101          ; I/O in, the KERNAL out: $35, as the game plays
        sta $01
        jmp ($a116)             ; the music, which goes on to $A6AC, the KERNAL
u4_irq_out:
        pla
        sta $01                 ; as it was
        pla
        tax
        pla
        rti

;;; $0314 during a load: the KERNAL's IRQ ($EA31) without its cursor and
;;; tape-motor code -- the clock, then from $EA7B the keyboard and the rest
u4_kirq:
        jsr $ffea
        jmp $ea7b

;;; TC_GUARD's receive banks the I/O in to read the raster, so it cannot
;;; run from the RAM under it with the rest of tclib.
!source "tcguard.s"

u4_glue_end:
!if u4_glue_end > $a674 {
        !error "u4 glue overruns BANKOUT at $A674 by ", u4_glue_end - $a674, " bytes"
}

;;; ==================================================================
;;; the rest, in the RAM under I/O
;;; ==================================================================
        * = $d000

u4_run:
        lda DK_CNT
        bne +
        rts                     ; zero blocks: nothing to do
+
        sta u4_left
        lda DK_ADR
        sta u4_mem
        lda DK_ADR+1
        sta u4_mem+1
        lda DK_BLK
        sta u4_blk
        lda DK_BLK+1
        sta u4_blk+1

        lda DK_OP
        cmp #$02
        bne u4_rd_first
        jmp u4_write

u4_rd_first:                    ; the temporary map, from its copy?
        jsr u4_istmap
        bne u4_read
        lda u4_tmv
        beq u4_read             ; none yet: its slot
        ldy #$00
        jsr u4_tcopy_in
        jsr u4_next
        dec u4_left
        bne u4_read
        rts

;;; ---- read --------------------------------------------------------
;;; Every block goes through the flash block map.  An entry is four bytes:
;;; the unit's 24-bit flash address, then the length of its zx02 stream --
;;; or 0 for a raw page, which only the save slots are.  MAP_BATCH entries at
;;; a time are read into u4_map, then each block is decoded straight out of
;;; flash into place.
;;;
;;; Every read is 2-bit with the screen on (TC_GUARD: each byte starts
;;; clear of the badlines) unless a sprite is enabled -- the creation's
;;; moongate -- when it is 1-bit as before.  No blanking either way.
u4_read:
u4_rd_batch:
        lda u4_left             ; n = min(left, MAP_BATCH)
        cmp #MAP_BATCH
        bcc +
        lda #MAP_BATCH
+       sta u4_n
        asl
        asl
        sta u4_nbytes
        sta tc_len
        lda #$00
        sta tc_len+1

        ldx u4_disk             ; tc_addr = map[disk] + blk * 4
        dex
        lda u4_blk
        sta tc_addr
        lda u4_blk+1
        asl tc_addr
        rol
        asl tc_addr
        rol
        sta tc_addr+1
        clc
        lda tc_addr
        adc u4_map_lo,x
        sta tc_addr
        lda tc_addr+1
        adc u4_map_mid,x
        sta tc_addr+1
        lda u4_map_hi,x
        adc #$00
        sta tc_addr+2
        lda #<u4_map
        sta tc_dest
        lda #>u4_map
        sta tc_dest+1
        jsr tc_read

        ldy #$00                ; y = byte offset of this block's entry
u4_rd_blk:
        sty u4_y
        lda u4_map,y
        sta tc_addr
        lda u4_map+1,y
        sta tc_addr+1
        lda u4_map+2,y
        sta tc_addr+2
        lda #$00
        sta tc_len+1
        lda u4_map+3,y
        beq u4_rd_raw
        sta tc_len
        lda u4_mem
        sta zx_dst
        lda u4_mem+1
        sta zx_dst+1
        jsr tc_stream_open
        jsr zx_unpack
        jsr tc_stream_close
        jmp u4_rd_next
u4_rd_raw:
        sta tc_len              ; one whole page
        inc tc_len+1
        lda u4_mem
        sta tc_dest
        lda u4_mem+1
        sta tc_dest+1
        jsr tc_read
u4_rd_next:
        inc u4_mem+1
        lda u4_y
        clc
        adc #$04
        tay
        cpy u4_nbytes
        bcc u4_rd_blk

        clc                     ; blk += n; left -= n
        lda u4_blk
        adc u4_n
        sta u4_blk
        bcc +
        inc u4_blk+1
+       sec
        lda u4_left
        sbc u4_n
        sta u4_left
        beq +
        jmp u4_rd_batch
+       rts

;;; ---- write -------------------------------------------------------
;;; Writes only ever land in the save slots.  Anything else is silently
;;; dropped rather than risking a corrupted game image -- there is no such
;;; call in the game (the only 'S' dispatches are chunks $7E/$7F/$80 and
;;; record $1A, and the hand-rolled block accessor at $0A7F only ever sets
;;; its op byte to 1).
u4_write:
        jsr u4_istmap           ; the temporary map: into its copy
        bne +
        jsr u4_tcopy_out
        lda #$01
        sta u4_tmv
        sta u4_tmd
        bne u4_wr_next          ; always
+       lda u4_blk              ; chunk $7F, a save: the copy to its slot first
        cmp #<QUIT_BLK
        bne +
        lda u4_blk+1
        cmp #>QUIT_BLK
        bne +
        jsr u4_tflush
+       jsr u4_setaddr
        lda u4_insave
        beq u4_wr_next
        lda #<u4_wpage
        ldx #>u4_wpage
        jsr u4_jwrite
u4_wr_next:
        jsr u4_next
        dec u4_left
        bne u4_write
        rts

;;; ==================================================================
;;; helpers
;;; ==================================================================

;;; tc_addr <- the save slot for block u4_blk, and u4_insave set, if the
;;; block is one of the five save blocks on the save disk.  Only the write
;;; path needs this: reads find the save slots through the block map, whose
;;; entries for those five blocks build.py points at the slots themselves.
u4_setaddr:
        lda #$00
        sta tc_addr             ; every unit is page aligned
        sta u4_insave

        lda u4_disk
        cmp #SAVE_DISK
        bne u4_sa_out
        sec                     ; index = u4_blk - SAVE_FIRST, in 0..4?
        lda u4_blk
        sbc #<SAVE_FIRST
        tax
        lda u4_blk+1
        sbc #>SAVE_FIRST
        bne u4_sa_out           ; borrowed, or more than 255 blocks past
        cpx #SAVE_COUNT
        bcs u4_sa_out

        txa                     ; page = savepage + index * 16
        asl
        asl
        asl
        asl
        clc
        adc u4_savepage
        sta tc_addr+1
        lda u4_savepage+1
        adc #$00
        sta tc_addr+2
        inc u4_insave
u4_sa_out:
        rts

;;; tc_len = one block, tc_dest = the current memory address

;;; a save slot written through the journal (asm/journal.s): tc_addr = the
;;; slot, A/X = what writes it there (erase, then the page), done twice
u4_jwrite:
        sta u4_jbody+1
        stx u4_jbody+2
        jsr jr_begin
        jsr u4_jbody
        jsr jr_commit
        jsr u4_jbody
        jmp jr_end
u4_jbody:
        jmp $0000

u4_wpage:                       ; the page at u4_mem
        jsr tc_erase_block      ; erases the 4 KiB block holding tc_addr
        jsr u4_setpage          ; tc_write takes its source from tc_dest
        jmp tc_write

u4_wtmap:                       ; the temporary map's copy
        jsr tc_erase_block
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        lda #<TMAP
        sta tc_dest
        lda #>TMAP
        sta tc_dest+1
        jmp tc_write

u4_setpage:
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        lda u4_mem
        sta tc_dest
        lda u4_mem+1
        sta tc_dest+1
        rts

;;; advance to the next block
u4_istmap:                      ; Z: block u4_blk of the save disk is chunk $7E's
        lda u4_disk
        cmp #SAVE_DISK
        bne +
        lda u4_blk
        cmp #<TMAP_BLK
        bne +
        lda u4_blk+1
        cmp #>TMAP_BLK
+       rts

u4_tcopy_in:                    ; the copy -> the page at u4_mem
        lda u4_mem+1
        sta u4_tci+2
        ldy #$00
-       lda TMAP,y
u4_tci: sta $ff00,y
        iny
        bne -
        rts

u4_tcopy_out:                   ; the page at u4_mem -> the copy
        lda u4_mem+1
        sta u4_tco+2
        ldy #$00
u4_tco: lda $ff00,y
        sta TMAP,y
        iny
        bne u4_tco
        rts

u4_tflush:                      ; a changed copy into chunk $7E's slot
        lda u4_tmd
        beq ++
        lda u4_blk              ; (the block being written is kept)
        pha
        lda u4_blk+1
        pha
        lda #<TMAP_BLK
        sta u4_blk
        lda #>TMAP_BLK
        sta u4_blk+1
        jsr u4_setaddr          ; the slot, on the save disk
        lda u4_insave
        beq +
        lda #<u4_wtmap
        ldx #>u4_wtmap
        jsr u4_jwrite
        lda #$00
        sta u4_tmd
+       pla
        sta u4_blk+1
        pla
        sta u4_blk
++      rts

u4_next:
        inc u4_mem+1
        inc u4_blk
        bne +
        inc u4_blk+1
+       rts

u4_tmv:      !byte 0            ; the temporary map's copy: there
u4_tmd:      !byte 0            ; ... and not yet in its slot
u4_blk:      !byte 0,0
u4_mem:      !byte 0,0
u4_left:     !byte 0
u4_insave:   !byte 0
u4_n:        !byte 0            ; map entries in this batch
u4_nbytes:   !byte 0            ; ... times two
u4_y:        !byte 0

PT_LONG = 1                     ; the cheats' table is longer than a page
!source "patch.s"

TCLIB_ORG = *
!source "tclib.s"

zx_getbyte = tc_stream_byte
!source "zx02s.s"

u4_map:      !fill MAP_BATCH * 4, 0     ; this batch's block map entries, 4 bytes each

pa_on:       !byte 0
pa_n:        !byte 0
pa_x:        !byte 0
!source "u4_patches.s"          ; generated by build.py: PT_TAB
!source "journal.s"             ; JOURNAL from build.py (regions.journal)

u4_lib_end:
!if u4_lib_end > TMAP {
        !error "u4 driver runs into the temporary map's copy at ", TMAP
}
!if u4_lib_end > $e000 {
        !error "u4 driver runs past the RAM under I/O"
}
