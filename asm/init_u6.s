;;; init_u6.s -- Ultima 6's init segment, loaded at $1000 as the last segment.
;;;
;;; The original boot, u6load, copies its driver to $C000 and jumps to the
;;; cold start at $C00C; the menu has already loaded the (patched) $C000
;;; image and the boot driver's second piece, so all that is left here is
;;; what the boot driver has no room for: the write log.  Nothing of the
;;; game is in memory yet, so this has RAM to spare ($2000-$30FF as
;;; buffers); the opening loads over all of it.
;;;
;;; THE LOG is U6's save region, split into two halves.  In each, pages
;;; grow up from the bottom and 20-byte directory entries grow down from the
;;; top, newest lowest.  A half's top slot is either its first ordinary
;;; entry or -- in a half compaction wrote -- a HEADER, key $FE "LOG", data
;;; a 16-bit generation and its complement.  An ordinary top entry means
;;; generation 0; an erased top slot, or a header whose check fails, means
;;; the half holds nothing.  The active half is the valid one with the
;;; higher generation (half 0 if neither is valid: a fresh cart).
;;;
;;; COMPACTION, when fewer than RESERVE pages are left: the newest version
;;; of every key is copied into the other half (erased first), its entries
;;; below the reserved top slot, then the header goes into that slot, then
;;; the old half is erased.  A power cut before the header is complete
;;; leaves the new half invalid and the old one active; after it, both are
;;; valid and the new one has the higher generation.  No step leaves no
;;; valid half.  The next compaction erases a half-written target anyway.
;;;
;;; A save cut short can leave pages written past the newest entry's, with
;;; no entry of their own.  Appending over them would corrupt the new pages
;;; -- flash only clears bits -- so the next free page skips every page that
;;; is not entirely erased.  And it starts from the newest entry whose pages
;;; lie inside the half, below the directory, so a torn entry cannot point
;;; it somewhere wild.
;;;
;;; Every boot pays for the scan, so it only probes the key byte of each
;;; directory slot; compaction reads the whole directory into RAM in one go.
;;;
;;; LOG_LO and LOG_HI (the region) come from build.py.

!source "u6.inc"
!source "u6boot_syms.inc"       ; generated: the boot driver's labels

HALF     = (LOG_HI - LOG_LO) / 2
RESERVE  = 128                  ; pages: a save is ~30 (4 chunk files, 4 BAMs, 12 sectors)
K_HEADER = $fe
LIVE     = $2000                ; the live entries, ENTRYLEN each
LIVEMAX  = ($3000 - LIVE) / ENTRYLEN
BUF      = $3000                ; one page
DIRBUF   = $4000                ; the directory, for compaction
DIRMAX_N = ($8000 - DIRBUF) / ENTRYLEN  ; (the menu is at $8700)
SCREEN   = $0400
BARLEN   = 30
BAR      = SCREEN + 40 * 14 + 5

        * = $1000
        sei
        ;; ---- a black screen until the opening's first picture: the cold
        ;; start blackens only the border, and its loads land in the
        ;; menu's text screen, which is still showing.  Background and
        ;; colour RAM black hide whatever arrives there.  ($01 is $35: I/O
        ;; is in.)
        lda #$00
        sta $d020
        sta $d021
        jsr colours
        ;; ---- which half ------------------------------------------------
        ldx #$00
        jsr topslot
        sta valid0
        lda tgen
        sta gen
        lda tgen+1
        sta gen+1
        ldx #$03
        jsr topslot
        beq pick0               ; half 1 invalid
        lda valid0
        beq pick1               ; half 0 invalid
        lda gen+1               ; both: half 1 if its generation is higher
        cmp tgen+1
        bcc pick1
        bne pick0
        lda gen
        cmp tgen
        bcs pick0
pick1:  lda tgen
        sta gen
        lda tgen+1
        sta gen+1
        ldx #$03
        !byte $2c               ; BIT abs: skip the ldx
pick0:  ldx #$00
        stx act
        jsr scan

        ;; ---- room left?  logdir and logdata in pages -------------------
        sec
        lda u6_logdir+1
        sbc u6_logdata+1
        tax
        lda u6_logdir+2
        sbc u6_logdata+2
        bne go                  ; 256 pages or more
        cpx #RESERVE
        bcs go
        jsr tidy
go:     lda xf_lvl              ; the Avatar from Ultima IV or V, if the
        beq +                   ; launcher's page asked for it
        jsr transfer
+       lda #$00                ; (black again, after a compaction's message)
        jsr colours
        jmp $c00c               ; the cold start (its drive-code upload is gone)

;;; ==================================================================
;;; transfer -- the launcher's page (page_u6t.s) pokes the Avatar it made
;;; from an Ultima IV or V save into xf_*: into the newest save area's
;;; S12 and S13, as a save would write them -- through the boot driver's
;;; own code, pages first, then their entries.  After the room check, so
;;; there is room for both.
;;; ==================================================================
transfer:
        lda #$0c
        jsr xf_get
        lda xf_str
        sta BUF+$8c             ; $578C strength, slot 0 (the Avatar)
        lda xf_dex
        sta BUF+$a3             ; $57A3 dexterity
        lda xf_lvl
        sta BUF+$ba             ; $57BA level
        lda xf_int
        sta BUF+$d1             ; $57D1 intelligence
        lda xf_hp
        sta BUF+$e8             ; $57E8 hit points
        sta BUF+$ff             ; $57FF their maximum
        jsr xf_put
        lda #$0d
        jsr xf_get
        lda xf_mp
        sta BUF+$44             ; $5844 magic points
        lda xf_xp
        sta BUF+$5b             ; $585B experience
        lda xf_xp+1
        sta BUF+$5c
        ;; (falls through)
;;; BUF -> the log, as the newest 1A T6 S(u6_s)
xf_put: lda #<BUF
        sta tc_dest
        lda #>BUF
        sta tc_dest+1
        jsr b_append            ; the page; b_data <- where it went
        jsr b_logkey
        ldx #DATALEN-4          ; the rest of the data zero
        lda #$00
-       sta b_data+3,x
        dex
        bpl -
        jmp b_entry_write

;;; 1A T6 S(A) -- the log's newest, else the original -- into BUF
xf_get: sta u6_s
        lda #$00                ; disk 0, the Surface
        sta u6_disk
        lda #$06
        sta u6_t
        jsr u6_sector_again     ; tc_addr: the original
        jsr b_logkey
        jsr b_lookup            ; a logged copy replaces it
        jmp rdpage

;;; poked by the launcher's page (page_u6t.s, in this order); a level of
;;; zero: nothing to transfer
xf_lvl: !byte 0
xf_str: !byte 0
xf_dex: !byte 0
xf_int: !byte 0
xf_hp:  !byte 0
xf_mp:  !byte 0
xf_xp:  !word 0

;;; the whole of colour RAM <- A
colours:
        ldx #$00
-       sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne -
        rts

;;; ==================================================================
;;; topslot -- read half X's top slot (X = 0 or 3) into ent.  A = 1 if the
;;; half is valid (Z clear), 0 if not; tgen = its generation.
;;; ==================================================================
topslot:
        lda #$00
        sta tgen
        sta tgen+1
        sec
        lda htop,x
        sbc #ENTRYLEN
        sta tc_addr
        lda htop+1,x
        sbc #$00
        sta tc_addr+1
        lda htop+2,x
        sbc #$00
        sta tc_addr+2
        jsr rdent
        lda ent
        cmp #$ff
        beq ts_bad
        cmp #K_HEADER
        bne ts_ok               ; an ordinary entry: generation 0
        lda ent+KEYLEN
        eor #$ff
        cmp ent+KEYLEN+2
        bne ts_bad              ; a torn header
        lda ent+KEYLEN+1
        eor #$ff
        cmp ent+KEYLEN+3
        bne ts_bad
        lda ent+KEYLEN
        sta tgen
        lda ent+KEYLEN+1
        sta tgen+1
ts_ok:  lda #$01
        rts
ts_bad: lda #$00
        rts

rdent:  lda #<ent               ; ENTRYLEN bytes from tc_addr
        ldx #>ent
        ldy #ENTRYLEN
        jmp u6_rdsmall

;;; ==================================================================
;;; scan -- the active half's directory: count it, and find the next
;;; free page
;;; ==================================================================
scan:
        lda #$00
        sta u6_dircount
        sta u6_dircount+1
        ldx act
        ldy #$00
-       lda htop,x              ; nothing found yet: an empty half
        sta u6_logdir,y
        lda hbase,x
        sta u6_logdata,y
        inx
        iny
        cpy #$03
        bne -
        ;; the directory's end: probe only the key byte of each slot down
        ;; from the top (7 bytes on the wire rather than 26)
sc_next:
        sec
        lda u6_logdir
        sbc #ENTRYLEN
        sta tc_addr
        lda u6_logdir+1
        sbc #$00
        sta tc_addr+1
        lda u6_logdir+2
        sbc #$00
        sta tc_addr+2
        lda #<ent
        ldx #>ent
        ldy #$01
        jsr u6_rdsmall
        lda ent
        cmp #$ff                ; no key starts with $FF: the end
        beq sc_end
        ldx #$02
-       lda tc_addr,x
        sta u6_logdir,x
        dex
        bpl -
        inc u6_dircount
        bne sc_next
        inc u6_dircount+1
        jmp sc_next

        ;; the next free page: where the newest entry's pages end -- the
        ;; newest that makes sense, so a torn entry cannot send it astray
sc_end: ldx #$02
-       lda u6_logdir,x
        sta walk,x
        dex
        bpl -
        lda u6_dircount
        sta left
        lda u6_dircount+1
        sta left+1
sc_ent: lda left
        ora left+1
        beq sc_done             ; none: the half's base
        ldx #$02
-       lda walk,x
        sta tc_addr,x
        dex
        bpl -
        jsr rdent
        lda ent
        cmp #K_HEADER           ; a header has no pages
        beq sc_older
        jsr pagesof
        clc                     ; its end, in pages
        lda ent+KEYLEN+1
        adc npages
        sta endp
        lda ent+KEYLEN+2
        adc npages+1
        sta endp+1
        bcs sc_older
        ldx act
        lda ent+KEYLEN+1        ; start >= the half's base ...
        cmp hbase+1,x
        lda ent+KEYLEN+2
        sbc hbase+2,x
        bcc sc_older
        lda u6_logdir+1         ; ... and end <= the directory
        cmp endp
        lda u6_logdir+2
        sbc endp+1
        bcc sc_older
        lda endp
        sta u6_logdata+1
        lda endp+1
        sta u6_logdata+2
        jmp sc_done
sc_older:
        jsr walk_up
        jmp sc_ent
sc_done:
        ;; skip pages a torn save left behind (never into the directory)
sk_loop:
        lda u6_logdata+1
        cmp u6_logdir+1
        lda u6_logdata+2
        sbc u6_logdir+2
        bcs sk_out
        ldx #$02
-       lda u6_logdata,x
        sta tc_addr,x
        dex
        bpl -
        jsr rdpage
        ldy #$00
-       lda BUF,y
        cmp #$ff
        bne sk_dirty
        iny
        bne -
sk_out: rts                     ; erased: the log goes on from here
sk_dirty:
        inc u6_logdata+1
        bne sk_loop
        inc u6_logdata+2
        jmp sk_loop

;;; walk += ENTRYLEN, left -= 1: the next older entry in flash
walk_up:
        clc
        lda walk
        adc #ENTRYLEN
        sta walk
        bcc +
        inc walk+1
        bne +
        inc walk+2
+       lda left
        bne +
        dec left+1
+       dec left
        rts

;;; npages <- the pages of the entry in ent: a file (F_LINKS) its count,
;;; a sector one
pagesof:
        ldx #$01
        ldy #$00
        lda ent+KEYLEN+5
        and #F_LINKS
        beq +
        ldx ent+KEYLEN+3
        ldy ent+KEYLEN+4
+       stx npages
        sty npages+1
        rts

;;; one page from tc_addr into BUF, and back
rdpage: jsr buflen
        jmp g_read
wrpage: jsr buflen
        jmp tc_write
buflen: lda #<BUF
        sta tc_dest
        lda #>BUF
        sta tc_dest+1
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        rts

;;; ==================================================================
;;; tidy -- compact the active half into the other one
;;; ==================================================================
tidy:
        ldx #$00                ; say so, it takes a while: white on black
        lda #$20
-       sta SCREEN,x
        sta SCREEN+$100,x
        sta SCREEN+$200,x
        sta SCREEN+$2e8,x
        inx
        bne -
        lda #$01
        jsr colours
-       lda msg,x
        beq +
        sta SCREEN+40*12+5,x
        inx
        bne -
+       ldx #BARLEN-1           ; the bar, empty
        lda #$2e                ; "."
-       sta BAR,x
        dex
        bpl -
        lda #<(2 * HALF / $1000)  ; its length in work units: a block
        sta total               ; erased is one, a page copied three --
        lda #>(2 * HALF / $1000)  ; about what they cost (58k and 185k
        sta total+1             ; cycles); the pages are added below
        ;; ---- the whole directory into RAM, in one read
        lda u6_dircount         ; (it cannot be bigger than DIRMAX: every
        cmp #<DIRMAX_N          ; entry but the header has a page; if it
        lda u6_dircount+1       ; were, leave the log as it is)
        sbc #>DIRMAX_N
        bcc +
        rts
+       lda u6_dircount         ; length = count * 20 = count * 16 + count * 4
        sta tc_len
        lda u6_dircount+1
        sta tc_len+1
        ldx #$02
-       asl tc_len
        rol tc_len+1
        dex
        bne -
        lda tc_len
        sta walk
        lda tc_len+1
        sta walk+1
        ldx #$02
-       asl tc_len
        rol tc_len+1
        dex
        bne -
        clc
        lda tc_len
        adc walk
        sta tc_len
        lda tc_len+1
        adc walk+1
        sta tc_len+1
        ldx #$02
-       lda u6_logdir,x
        sta tc_addr,x
        dex
        bpl -
        lda #<DIRBUF
        sta tc_dest
        sta td_dl+1
        lda #>DIRBUF
        sta tc_dest+1
        sta td_dl+2
        jsr g_read

        ;; ---- the live entries: walking up from the newest, each key the
        ;; first time it is seen
        lda #$00
        sta nlive
        lda u6_dircount
        sta left
        lda u6_dircount+1
        sta left+1
td_walk:
        lda left
        ora left+1
        bne +
        jmp td_copy
+       ldy #ENTRYLEN-1
td_dl:  lda $ffff,y
        sta ent,y
        dey
        bpl td_dl
        lda ent
        cmp #K_HEADER
        beq td_next
        lda #<LIVE              ; seen already?
        sta td_lv+1
        lda #>LIVE
        sta td_lv+2
        ldx nlive
        beq td_add
td_cmp: ldy #KEYLEN-1
td_lv:  lda $ffff,y
        cmp ent,y
        bne td_diff
        dey
        bpl td_lv
        bmi td_next             ; yes: this is an older version
td_diff:
        jsr lv_step
        dex
        bne td_cmp
td_add: lda nlive               ; td_lv now points past the last live one
        cmp #LIVEMAX
        bcs td_abort
        lda td_lv+1
        sta td_st+1
        lda td_lv+2
        sta td_st+2
        ldy #ENTRYLEN-1
-       lda ent,y
td_st:  sta $ffff,y
        dey
        bpl -
        inc nlive
        jsr pagesof             ; its pages, three units each
        ldx #$03
-       clc
        lda total
        adc npages
        sta total
        lda total+1
        adc npages+1
        sta total+1
        dex
        bne -
td_next:
        clc                     ; the next older entry
        lda td_dl+1
        adc #ENTRYLEN
        sta td_dl+1
        bcc +
        inc td_dl+2
+       lda left
        bne +
        dec left+1
+       dec left
        jmp td_walk
td_abort:
        rts                     ; cannot happen (97 keys at most): leave it

        ;; ---- copy them into the other half -------------------------------
td_copy:
        lda act
        eor #$03
        sta tgt
        tax
        jsr erase_half
        ldx tgt                 ; data from its base, entries from below
        ldy #$00                ; its top slot
-       lda hbase,x
        sta ndata,y
        lda htop,x
        sta ndir,y
        inx
        iny
        cpy #$03
        bne -
        jsr ndir_down
        lda #<LIVE
        sta td_lv+1
        lda #>LIVE
        sta td_lv+2
        lda nlive
        sta left
td_unit:
        lda left
        bne +
        jmp td_header
+       lda td_lv+1             ; the next live entry into ent
        sta td_ld+1
        lda td_lv+2
        sta td_ld+2
        ldy #ENTRYLEN-1
td_ld:  lda $ffff,y
        sta ent,y
        dey
        bpl td_ld
        jsr pagesof
        ldx #$02                ; its pages move from where they are to
-       lda ent+KEYLEN,x        ; ndata, which is its new address
        sta walk,x
        lda ndata,x
        sta ent+KEYLEN,x
        dex
        bpl -
td_page:
        lda npages
        ora npages+1
        beq td_entry
        ldx #$02
-       lda walk,x
        sta tc_addr,x
        dex
        bpl -
        jsr rdpage
        ldx #$02
-       lda ndata,x
        sta tc_addr,x
        dex
        bpl -
        jsr wrpage
        jsr tick
        jsr tick
        jsr tick
        inc walk+1
        bne +
        inc walk+2
+       inc ndata+1
        bne +
        inc ndata+2
+       lda npages
        bne +
        dec npages+1
+       dec npages
        jmp td_page
td_entry:
        jsr ndir_down           ; then its entry, below the previous one
        jsr wrent
        jsr lv_step
        dec left
        jmp td_unit

td_header:
        ;; all copied: the header, into the top slot, last
        ldx #KEYLEN+DATALEN-1
        lda #$00
-       sta ent,x
        dex
        bpl -
        ldx #$03
-       lda hdr_key,x
        sta ent,x
        dex
        bpl -
        clc
        lda gen
        adc #$01
        sta ent+KEYLEN
        eor #$ff
        sta ent+KEYLEN+2
        lda gen+1
        adc #$00
        sta ent+KEYLEN+1
        eor #$ff
        sta ent+KEYLEN+3
        ldx #$02                ; (ndir is the lowest entry: keep it)
-       lda ndir,x
        sta walk,x
        dex
        bpl -
        ldx tgt
        ldy #$00
-       lda htop,x
        sta ndir,y
        inx
        iny
        cpy #$03
        bne -
        jsr ndir_down
        jsr wrent
        ldx act                 ; and only now the old half goes
        jsr erase_half

        ;; the log goes on in the new half
        ldx #$02
-       lda walk,x
        sta u6_logdir,x
        lda ndata,x
        sta u6_logdata,x
        dex
        bpl -
        ldx nlive               ; its entries: the live ones, the header
        inx
        stx u6_dircount
        lda #$00
        sta u6_dircount+1
        lda tgt
        sta act
        rts

;;; write ent at ndir
wrent:  ldx #$02
-       lda ndir,x
        sta tc_addr,x
        dex
        bpl -
        lda #<ent
        sta tc_dest
        lda #>ent
        sta tc_dest+1
        lda #ENTRYLEN
        sta tc_len
        lda #$00
        sta tc_len+1
        jmp tc_write

hdr_key: !byte K_HEADER, $4c, $4f, $47     ; "LOG" in ASCII

;;; td_lv += ENTRYLEN
lv_step:
        clc
        lda td_lv+1
        adc #ENTRYLEN
        sta td_lv+1
        bcc +
        inc td_lv+2
+       rts

;;; ndir -= ENTRYLEN
ndir_down:
        sec
        lda ndir
        sbc #ENTRYLEN
        sta ndir
        lda ndir+1
        sbc #$00
        sta ndir+1
        lda ndir+2
        sbc #$00
        sta ndir+2
        rts

;;; erase half X (0 or 3)
erase_half:
        ldy #$00
-       lda hbase,x
        sta tc_addr,y
        inx
        iny
        cpy #$03
        bne -
        lda #<(HALF / $1000)
        sta blocks
-       jsr tc_erase_block
        jsr tick
        clc
        lda tc_addr+1
        adc #$10
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       dec blocks
        bne -
        rts

;;; ---- the halves, little endian: half 0 at +0, half 1 at +3 -----------
hbase:  !24 LOG_LO, LOG_LO + HALF
htop:   !24 LOG_LO + HALF, LOG_HI

msg:    !scr "tidying the world of ultima vi", 0

;;; one unit of work done: the bar grows by BARLEN / total cells, kept exact
;;; with a remainder, as a line is drawn
tick:   clc
        lda acc
        adc #BARLEN
        sta acc
        bcc tk_loop
        inc acc+1
tk_loop:
        lda acc                 ; a whole cell's worth?
        cmp total
        lda acc+1
        sbc total+1
        bcc tk_out
        lda acc
        sbc total               ; (carry set)
        sta acc
        lda acc+1
        sbc total+1
        sta acc+1
        ldx cell
        cpx #BARLEN
        bcs tk_loop
        lda #$a0                ; a solid block
        sta BAR,x
        inc cell
        jmp tk_loop
tk_out: rts

act:    !byte 0
tgt:    !byte 0
valid0: !byte 0
gen:    !word 0
tgen:   !word 0
npages: !word 0
endp:   !word 0
nlive:  !byte 0
total:  !word 0
acc:    !word 0
cell:   !byte 0
left:   !word 0
blocks: !byte 0
walk:   !fill 3, 0
ndata:  !fill 3, 0
ndir:   !fill 3, 0
ent:    !fill ENTRYLEN, 0

!if HALF & $fff { !error "the log's halves must be whole erase blocks" }
!if (HALF / $1000) > 255 { !error "a half is too big for erase_half" }

;;; ==================================================================
;;; g_read -- the compaction's reads, 2-bit with the screen on:
;;; tclib's TC_GUARD receive (tcguard.s, bare; its port values, as they
;;; default, are the boot driver's: $01 = $20 in a transfer, the DDR $2F),
;;; through the boot driver's own command routines.  Interrupts are off here
;;; from the start, and no sprite is on (the menu took them down).  Writes
;;; stay 1-bit: the protocol has no fast write.  tc_len bytes from tc_addr
;;; to tc_dest.
;;; ==================================================================
CMD_READ_FLASH_FAST = $11
g_read: jsr tc_enter
        lda #CMD_READ_FLASH_FAST
        jsr tc_sendbyte
        jsr tc_send_addr_len
        lda tc_dest
        sta gr_st+1
        lda tc_dest+1
        sta gr_st+2
gr_loop:
        lda tc_len
        ora tc_len+1
        beq gr_done
        jsr tc_getbyte_guard
gr_st:  sta $ffff
        inc gr_st+1
        bne +
        inc gr_st+2
+       lda tc_len
        bne +
        dec tc_len+1
+       dec tc_len
        jmp gr_loop
gr_done:
        jmp tc_leave

TC_GUARD      = 1
TC_GUARD_BARE = 1
BIT_SENSE     = $10
;;; tcfast.s's nibble table must stay inside a page (it checks); it is
;;; G_TAB bytes into tcguard.s, so pad in front when it would cross
G_TAB = $43
!if ((* + G_TAB) & $ff) > $f0 {
        !fill $100 - ((* + G_TAB) & $ff), $00
}
g_guard:
!source "tcguard.s"
!if tc_nibbletab - g_guard != G_TAB {
        !error "G_TAB is ", tc_nibbletab - g_guard, " now"
}
