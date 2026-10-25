;;; u2drv.s -- Ultima 2 disk driver replacement.
;;;
;;; ULTIMA ($5000-$8A8F) contains no KERNAL references at all: it reaches the
;;; drive only through four entries in SUBS' 59-entry jump table at $4000.
;;; Those four entries are the whole seam, and build.py repoints them here:
;;;
;;;   $408D  LOAD named file   inline: name,0,addr           -> u2_load
;;;   $4090  SAVE named file   inline: name,0,start,end      -> u2_save
;;;   $40AB  raw U1/U2 block   $FB track $FC sector $FD op   -> u2_block
;;;                            $FE/$FF buffer
;;;   $40AE  OPEN 15,8,15      (only ever called from the two above) -> RTS
;;;
;;; The rest of SUBS is left as it is, so the inline-parameter helpers stay
;;; available and this code calls them rather than reimplementing the
;;; convention.  (Three more jumps go to u2step.s: the footstep's.)
;;;
;;;   $4BF0  return address -> $2B/$2C, i.e. a pointer to the inline block
;;;   $4C05  strlen of the name -> $0E
;;;   $4C1C  A = bytes of parameter after the name; steps the return address
;;;          past the whole block, restores the raster IRQ and returns
;;;   $4C32  restore the raster split from its table at $47C6-$47CF
;;;   $4C47  print "ONE MOMENT PLEASE!"
;;;
;;; WHERE THIS LIVES.  $B100-$BFFF, which is RAM whenever $01 = $36, and the
;;; game sets $01 = $36 and never puts it back (there are exactly four writes
;;; to $01 in the whole game, all $36).  The map cache under the BASIC ROM is
;;; $A000-$B0FF exactly -- $6809 and $685F copy $1000-$1FFF to $A000 and
;;; $8F00-$8FFF to $B000, and stop there -- so $B100 up is free.  The init
;;; stub sets $01 = $36 before anything runs, because the original boot chain
;;; starts at $37 and would have BASIC ROM sitting on top of this code.
;;;
;;; (The other obvious hole, $2000-$2FFF, is NOT free: $7BA5 fills
;;; $2000-$21FF with $FF at game start.  The per-game notes list that range
;;; as unaccounted for; it is game state.)
;;;
;;; COMPRESSION.  Units that shrink are stored zx02-crunched and marked
;;; with F_COMP in the disk byte; the length field is then the *compressed*
;;; length, which is all tc_stream_open needs -- the stream ends itself, so
;;; the decrunched size never has to be recorded.  Crunched units do not
;;; blank the screen: the 1-bit protocol has no timing constraint, so a
;;; compressed load is also a load without the display flicker.
;;;
;;; WHICH DISK.  Both disks carry files with the same name and different
;;; contents -- MAP 10, MAP 15, MAP 20, MAP 30, MAP 32, MAP 40, MAP 41,
;;; MAP 45, MON 32, MON 41, TLK 32, TLK 41.  The selector is $8E37, the
;;; planet number in the player record: 0 means Earth and the Player disk,
;;; anything else a planet and the Galactic disk.  ($7B42 proves it -- the
;;; game reads T35/S16 and compares the sector's "not a player disk" marker
;;; against $8E37.)  So the lookup runs twice: once demanding the disk $8E37
;;; asks for, then once accepting either.  That is what a patient user with
;;; both disks in two drives would get, minus the swapping.

TC_NO_CMDMODE = 1               ; the menu entered it; command mode persists
U2_FAST       = 0               ; 1 = READ_FLASH_FAST + blank, 0 = tc_read
TC_NO_FAST    = 1               ; no blanking: TC_GUARD's tc_read is 2-bit
TC_GUARD      = 1               ; with the screen on (1-bit if a sprite is)
TC_NMI_HOLD   = 1               ; and no RESTORE inside a timed byte

;;; SUBS routines we call rather than reimplement
SUBS_PARAMS  = $4bf0            ; $2B/$2C <- pointer to the inline block
SUBS_STRLEN  = $4c05            ; $0E <- length of the name
SUBS_RETURN  = $4c1c            ; A = trailing parameter bytes; returns
SUBS_RASTER  = $4c32            ; restore the raster split
SUBS_MOMENT  = $4c47            ; "ONE MOMENT PLEASE!"

NAMEPTR = $2b                   ; SUBS' own pointer to the inline parameters
NAMELEN = $0e                   ; SUBS' own name length

PLANET  = $8e37                 ; player record: 0 = Earth, else planet number

;;; raw block parameters, in zero page
BLK_TRK = $fb
BLK_SEC = $fc
BLK_OP  = $fd                   ; 1 = read (U1), 2 = write (U2); status on exit
BLK_BUF = $fe                   ; word

REC_TRACK  = 35                 ; the player record: raw T35/S16, no directory
REC_SECTOR = 16
STATUS_OK  = $30                ; '0' -- what $4F5C would have left in $FD

;;; one table entry, filled in by build.py
U2_ENTRY   = 13                 ; name 8, page 2, length 2, disk 1
U2_ENTRIES = 124                ; capacity; build.py asserts the real count fits
F_WRITE    = %10000000          ; in the disk byte: this file has a save slot
F_COMP     = %01000000          ; ...and: stored zx02-crunched
M_DISK     = %00000011

        * = $b100
        jmp u2_boot             ; $B100 -- the init stub's one entry point:
                                ; tclib, then the save log (u2log.s)

;;; ==================================================================
;;; $408D -- LOAD "name" -> addr
;;; ==================================================================
u2_load:
        jsr SUBS_MOMENT         ; before masking: it wants the raster split
        jsr u2_enter
        jsr SUBS_PARAMS
        jsr SUBS_STRLEN
        jsr u2_find
        bcs u2_ld_done          ; unknown name: leave memory alone

        ldy #$08                ; flash page -> tc_addr
        jsr u2_ent
        sta tc_addr+1
        ldy #$09
        jsr u2_ent
        sta tc_addr+2
        lda #$00
        sta tc_addr
        ldy #$0a                ; length
        jsr u2_ent
        sta tc_len
        ldy #$0b
        jsr u2_ent
        sta tc_len+1

        ldy NAMELEN             ; destination follows the name's NUL
        iny
        lda (NAMEPTR),y
        sta tc_dest
        iny
        lda (NAMEPTR),y
        sta tc_dest+1

        ldy #$0c                ; raw, or crunched straight out of flash?
        jsr u2_ent
        and #F_COMP
        beq +
        jsr zxd_unpack
        jmp u2_ld_done
+       jsr u2_fetch

u2_ld_done:
        jsr SUBS_RASTER         ; display back first, then interrupts
        jsr u2_leave
        lda #$02                ; two parameter bytes after the name
        jmp SUBS_RETURN

;;; ==================================================================
;;; $4090 -- SAVE "name" <- start..end
;;;
;;; Only MOB xx and MON xx on the player disk are writable, and the game
;;; only saves while $8E37 is zero ($68AE returns early otherwise).  A write
;;; to anything else is dropped rather than risking the read-only image: the
;;; original would scratch-and-create the file, but the only names it can
;;; invent are MOB xy with y != 0, which nothing ever loads back ($67F1
;;; skips the MOB load unless both $8E14 and $8E37 are zero).
;;; ==================================================================
u2_save:
        jsr SUBS_MOMENT
        jsr u2_enter
        jsr SUBS_PARAMS
        jsr SUBS_STRLEN
        jsr u2_find
        bcs u2_sv_done
        ldy #$0c
        jsr u2_ent
        and #F_WRITE
        beq u2_sv_done          ; read-only file: silently ignore

        ldy NAMELEN             ; start address
        iny
        lda (NAMEPTR),y
        sta tc_dest
        sta u2_start
        iny
        lda (NAMEPTR),y
        sta tc_dest+1
        sta u2_start+1
        iny                     ; end address; length = end - start
        sec
        lda (NAMEPTR),y
        sbc u2_start
        sta tc_len
        iny
        lda (NAMEPTR),y
        sbc u2_start+1
        sta tc_len+1

        lda u2_idx              ; into the log as unit index + 1
        clc
        adc #$01
        jsr u2_append
u2_sv_done:
        jsr SUBS_RASTER
        jsr u2_leave
        lda #$04                ; four parameter bytes after the name
        jmp SUBS_RETURN

;;; ==================================================================
;;; $40AB -- raw U1/U2 block
;;;
;;; The player record is the only block the game ever touches this way, at
;;; track 35 sector 16 with no directory entry.  The other user of this entry
;;; was the copy-protection read of track 18 sector 18, and build.py stubs
;;; that out at its source ($CED6) so it never gets here.
;;; ==================================================================
u2_block:
        jsr u2_enter
        lda BLK_TRK
        cmp #REC_TRACK
        bne u2_blk_done
        lda BLK_SEC
        cmp #REC_SECTOR
        bne u2_blk_done

        lda #$00
        sta tc_addr
        sta tc_len
        lda u2_recpage
        sta tc_addr+1
        lda u2_recpage+1
        sta tc_addr+2
        lda #$01                ; one 256-byte sector
        sta tc_len+1
        lda BLK_BUF
        sta tc_dest
        lda BLK_BUF+1
        sta tc_dest+1

        lda BLK_OP
        cmp #$02
        beq u2_blk_write
        jsr u2_fetch
        jmp u2_blk_done
u2_blk_write:
        lda #$00                ; the log's unit 0
        jsr u2_append

u2_blk_done:
        lda #STATUS_OK          ; $4F5C used to leave the error digit here
        sta BLK_OP
        jsr SUBS_RASTER
        jmp u2_leave

;;; $40AE -- OPEN 15,8,15.  Only the two routines above ever called it.
u2_cmdchan:
        rts

;;; ==================================================================
;;; entry/exit: the caller's I flag, and the display
;;;
;;; The raster split rewrites $D011 from its table every frame, so clearing
;;; DEN is pointless while interrupts are live -- and tc_blank has to wait a
;;; whole frame for the VIC to notice.  Masking interrupts for the duration
;;; is what the original did too, by way of the KERNAL's serial routines;
;;; $4C32 is its own way of putting the split back, and u2_leave's callers
;;; reach it through $4C1C.
;;; ==================================================================
u2_enter:
        jsr st_flush            ; a footstep in flight ends first (u2step.s)
        php
        pla
        sta u2_flags
        sei
        rts

u2_leave:
        lda u2_flags
        and #%00000100
        bne +
        cli
+       rts

;;; read tc_len bytes from tc_addr to tc_dest, with a quiet display
u2_fetch:
        lda $01
        sta u2_save01
        ora #%00000100          ; CHAREN only: never LORAM/HIRAM, which would
        sta $01                 ; bank ROM over this code at $B100
!if U2_FAST = 1 {
        jsr tc_blank
        jsr tc_read_fast
        jsr tc_unblank
} else {
        jsr tc_read
}
        lda u2_save01
        sta $01
        rts

;;; ==================================================================
;;; name lookup
;;;
;;; u2_e is the entry cursor, a self-modified absolute address -- the table
;;; is 1664 bytes so an index will not do, and tclib's no-zero-page rule
;;; applies here too: $2B/$2C and $0E are SUBS', and the cache copy at $6809
;;; owns $0A/$0B and $3D/$3E.
;;; ==================================================================
u2_ent:                         ; A <- entry byte Y of the current entry
u2_e:   lda $ffff,y
        rts

u2_find:
        lda PLANET              ; which disk does the game think is in?
        beq +
        lda #$01                ; a planet -> the Galactic disk
        bne ++
+       lda #$02                ; Earth -> the Player disk
++      sta u2_want

        lda #$00                ; pass 1: insist on that disk
        sta u2_any
        jsr u2_scan
        bcc u2_f_out
        lda #$01                ; pass 2: accept the other one
        sta u2_any
        jsr u2_scan
u2_f_out:
        rts

u2_scan:
        lda #<u2_table
        sta u2_e+1
        lda #>u2_table
        sta u2_e+2
        lda #$00
        sta u2_idx
u2_s_loop:
        lda u2_idx
        cmp u2_count
        bcs u2_s_miss
        jsr u2_match
        bcc u2_s_hit
        clc                     ; step to the next entry
        lda u2_e+1
        adc #U2_ENTRY
        sta u2_e+1
        bcc +
        inc u2_e+2
+       inc u2_idx
        jmp u2_s_loop
u2_s_hit:
        clc
        rts
u2_s_miss:
        sec
        rts

;;; C=0 if the current entry matches the caller's name (and disk, on pass 1)
u2_match:
        ldy #$00
u2_m_loop:
        cpy NAMELEN             ; past the name's NUL the caller's bytes are
        bcc u2_m_have           ; the address parameters, so supply NULs
        beq u2_m_have
        lda #$00
        jmp u2_m_cmp
u2_m_have:
        lda (NAMEPTR),y
u2_m_cmp:
        sta u2_ch
        jsr u2_ent
        cmp u2_ch
        bne u2_m_no
        iny
        cpy #$08
        bne u2_m_loop

        lda u2_any              ; name matches; is this the right disk?
        bne u2_m_yes
        ldy #$0c
        jsr u2_ent
        and #M_DISK
        cmp u2_want
        bne u2_m_no
u2_m_yes:
        clc
        rts
u2_m_no:
        sec
        rts

;;; ==================================================================
u2_want:     !byte 0
u2_any:      !byte 0
u2_idx:      !byte 0
u2_ch:       !byte 0
u2_flags:    !byte 0
u2_save01:   !byte 0
u2_start:    !byte 0,0

;;; build.py fills these in; $FFFF is a placeholder it asserts against
u2_recpage:  !word $ffff        ; flash page of the player record (its seed;
                                ; lg_init points it at the log's newest)
u2_count:    !byte 0            ; live entries in the table below
u2_table:    !fill U2_ENTRY * U2_ENTRIES, 0

TCLIB_ORG = *
!source "tclib.s"
!source "zxdecr.s"

;;; ==================================================================
;;; the save log (u2log.s), in the RAM under I/O: banked in for a call
;;; ==================================================================
u2_boot:                        ; the init stub's entry: tclib, then the log
        jsr tc_init
        ldx #<lg_init
        ldy #>lg_init
        bne lg_run              ; (always)
u2_append:                      ; A = unit; tc_dest/tc_len = its data
        ldx #<lg_append
        ldy #>lg_append
lg_run: stx lg_to+1             ; (A passes through)
        sty lg_to+2
        ldx $01
        stx lg_01
        ldx #$34                ; all RAM: interrupts are already off
        stx $01
lg_to:  jsr $ffff
        ldx lg_01
        stx $01
        rts
lg_01:  !byte 0

;;; INTRO hands over to ULTIMA here instead of at $5000 (build.py): the
;;; launcher's options go in first, now that ULTIMA is loaded.
u2_go:  jsr pt_apply
        jmp $5000
!source "patch.s"
pt_opts: !byte 0                ; the launcher pokes it: patches.py's bits
pa_on:   !byte 0
pa_n:    !byte 0
pa_x:    !byte 0
!source "u2_patches.s"          ; generated by build.py: PT_TAB
pw_on:   !byte 0                ; the launcher's X: $80 = on (a launch poke);
                                ; its code is in SUBS (u2powers.s)
!source "u2clamp.s"             ; counts stop at 99 and 9999, the launcher's V
!source "u2step.s"              ; the footstep from the raster IRQ

u2_end:
!if u2_end > $c000 {
        !error "u2 driver overruns INTRO at $C000 by ", u2_end - $c000, " bytes"
}

        * = $d000               ; its own segment (build.py slices it off)
!source "u2log.s"
