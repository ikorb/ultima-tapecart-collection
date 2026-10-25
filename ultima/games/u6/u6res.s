;;; u6res.s -- Ultima 6's in-game driver, the resident part.
;;;
;;; Lives in `game`'s own disk code, which it replaces: the old loader at
;;; $2989-$2B4D and the disk-ID check and swap prompt at $2823-$28CD.  The
;;; entry points stay where the game calls them:
;;;
;;;   $29BE  the loader: X/Y -> a command string (U6 notes 5b).  Also reached
;;;          through $0263 (JMP $29BE), and from $27FA/$2804/$2809, which are
;;;          left as they are and still set up $0203-$0209 and call it.
;;;   $2823  "is disk X in?" -- X = 0 Surface, 2 Dungeon, 4 CA, 6 CB, 8 CC,
;;;          10 GA.  The original sent `#xx` and prompted until it matched;
;;;          every disk is in flash, so this only remembers which one.
;;;          ($2813, which picks Surface or Dungeon by $10 and sets $A0 on the
;;;          way, is left alone and falls into it.)
;;;
;;; Everything frequent is resident: the sector read `^` -- 1680 of 2239
;;; commands in a traced session -- straight from a raw block map.  The rest
;;; (named loads, `!`, `&`, reads of the few sectors the game writes) is
;;; u6bulk.s, fetched from flash into the idle half of the sprite double
;;; buffer on each such call; see u6.inc.  Its state therefore lives here.
;;;
;;; Interrupts stay on, as with the original drive: TC_IRQ_ON, both IRQ
;;; handlers patched to keep $01 bits 3/4, and no zero page anywhere.

TC_NO_CMDMODE = 1
TC_NO_FAST    = 1
TC_NO_ERASE   = 1
TC_NO_STREAM  = 1               ; both live in u6bulk (TC_EXTRAS_ONLY), the
TC_NO_WRITE   = 1               ; only code that streams or writes
TC_IRQ_ON     = 1
TC_NO_C0      = 1
TC_STATIC_01  = $34
TC_STATIC_00  = $2f

!source "u6.inc"
TC_SCREEN_LED = LIGHT_CELL      ; the access light (u6.inc)
TC_SCREEN_ON  = LIGHT_ON
TC_SCREEN_OFF = LIGHT_OFF
U6_OTHER = u6_bulk
U6_EXIT01 = $34
U6_CB_RTS_AT = $29b6            ; $02AE: JMP $29B6, a lone RTS -- u6_cb's
                                ; serves it (see u6io_small.s)

;;; ==================================================================
;;; piece A: $2823-$28CD
;;; ==================================================================
        * = $2823
u6_setdisk:
        cpx #$04                ; only Surface and Dungeon have sectors;
        bcs +                   ; the other disks are read by name
        txa
        lsr
        sta u6_disk
+       stx u6_keep             ; (X is 0-10: no half) -- see u6_bulk
        clc                     ; the right disk is always in
        rts

!source "u6io_sector.s"

;;; the resident's state that fits here (the rest is after tclib)
u6_t:        !byte 0
u6_s:        !byte 0
u6_off:      !byte 0
u6_cnt:      !byte 0
u6_blk:      !byte 0            ; (the high byte of t * 21 + s)
u6_skey:     !fill KEYLEN, 0    ; the open write session's file, as "/NAME"
u6_map_lo:   !byte $ff, $ff     ; Surface, Dungeon: their block maps
u6_map_mid:  !byte $ff, $ff     ; (filled in by the build)
u6_map_hi:   !byte $ff, $ff
u6_sdir:     !fill 5, $ff       ; the static directory: address (3), count (2)
u6_logdir:   !fill 3, $ff       ; the log's directory, from its newest entry:
u6_dircount: !word $ffff        ;   address (3), count (2) -- adjacent, as
                                ;   DIR_SETPARAMS wants them
u6_open:     !byte 0            ; a write session (after `!`) is open
u6_scount:   !byte 0            ;   pages written in it
u6_sstart:   !fill 3, 0         ;   where they start
u6_bulkfl:   !fill 7, $ff       ; flash addresses, high byte first: u6bulk
                                ; assembled for $DC00, a spare byte, then
                                ; for $D800 (u6_bulk indexes it 0 or 4)
u6_keep:     !byte 0            ; the half that still holds u6bulk, if any
u6_ment:     !fill 4, 0         ; the block map entry: address (3), length
u6_mlen = u6_ment + 3
u6_logdata:  !fill 3, $ff       ; the next free log page

u6_piece_a_end:
!if u6_piece_a_end > $28ce {
        !error "u6 resident piece A runs into the keyboard scan at $28CE by ", u6_piece_a_end - $28ce
}

;;; ==================================================================
;;; piece B: $2989-$2B4D, with the entry at exactly $29BE
;;; ==================================================================
        * = $2989

!source "u6io_small.s"

!if * > $29be {
        !error "u6 resident: the helpers run into the entry at $29BE by ", * - $29be
}
        !fill $29be - *, $ea

;;; ==================================================================
;;; $29BE -- the loader.  X/Y -> the command.
;;; ==================================================================
u6_cmd:
        stx u6_c+1
        sty u6_c+2
        stx u6_cmd0
        sty u6_cmd0+1
        lda #$34                ; all RAM: the idle half is under I/O
        sta $01
!source "u6io_read.s"

;;; fetch u6bulk into the idle sprite half and run it -- unless that half
;;; still holds it.  u6bulk sets u6_keep to its half for `!`, `&` and reads of
;;; the save area, and clears it for a load by name; $2823 clears it too.
;;; Those commands only come in the save ($3E83) and the state load
;;; ($3EBD), which end in $2813 -> $2823 and render nothing before it (a
;;; save, watched in VICE: no store into $D800-$DFFF but the driver's), so
;;; nothing can have drawn into the half meanwhile.  A save was 37 fetches
;;; of the whole kilobyte at 1 bit, 16.6 of its 21.6 s; now two.
u6_bulk:
        lda u6_cmd0             ; it re-reads the command from the start
        sta u6_c+1
        lda u6_cmd0+1
        sta u6_c+2
        lda $27                 ; bit 4 set: B ($70-$7F) is on screen, so
        and #$10                ; A is idle: X = 4, $D8; clear: B is
        lsr                     ; idle, X = 0, $DC
        lsr
        tax
        eor #>BULK_B
        sta u6_bjmp+2
        cmp u6_keep
        beq u6_bjmp             ; still there
        sta tc_dest+1
        ldy #$02
-       lda u6_bulkfl,x
        sta tc_addr,y
        inx
        dey
        bpl -
u6_bulk_rd:                     ; (u6bulk's b_pack comes in here, u6pack
        lda #$00                ; goes back through u6_bulk)
        sta tc_dest
        sta tc_len
        lda #>BULKMAX
        sta tc_len+1
        jsr tc_read
u6_bjmp:
        jmp BULK_A              ; patched: the half just filled

TCLIB_ORG = *
!source "tclib.s"

;;; ---- state: everything that must outlive one on-demand call ------
u6_cmd0:     !word 0            ; the command's address
u6_disk:     !byte 0            ; 0 Surface, 1 Dungeon
;;; (the rest of the state is in piece A, which has the room since the LED
;;; commands made tclib longer)

!if (BULK_A + $400 != BULK_B) or ((BULK_B & $400) = 0) {
        !error "u6_bulk's EOR picks the halves: BULK_B must be BULK_A + $400"
}

u6_piece_b_end:
!if u6_piece_b_end > $2b4e {
        !error "u6 resident piece B runs past $2B4D by ", u6_piece_b_end - $2b4e
}
