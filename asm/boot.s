;;; boot.s -- the first stage: what the tapecart's own initial loader loads.
;;;
;;; The cart's loadinfo (address, length, call address) is written only by a
;;; full .tcrt flash; "Write data file" leaves it alone.  So it must never
;;; have to change: it loads this, BOOT_LEN bytes from regions.BOOT_PRG, and
;;; this loads the launcher -- the menu's PRG, font to export tables -- from
;;; wherever the locator at regions.LAUNCHER_LOC says, at whatever length,
;;; and starts it at its origin ($8700, JMP start).  The menu enters command
;;; mode again itself (tc_cmdmode drops the cart to streaming mode first, so
;;; a second entry is fine) and is otherwise unchanged.
;;;
;;; Before that, with nothing yet started that reads a save:
;;; - the stamp: the settings page must start "UCFG" and carry this build's
;;;   save layout (regions.LAYOUT) at SET_LAYOUT, which the full image seeds.
;;;   If not -- an update image flashed over a cart whose saves are laid out
;;;   for another build -- it says so and starts nothing.
;;; - the journals (asm/journal.s): a save a power cut interrupted after its
;;;   journal was complete is copied into its slot, and the journal erased.
;;;
;;; It runs where the launcher's staging buffers are ($0800-$3FFF): nothing
;;; of the launcher loads there.  The read is tclib's 2-bit one with the
;;; screen on (TC_GUARD), as the games' bulk loads; no sprite is on at power-on.

buf = $2000                     ; a page (the launcher's staging buffers)

TC_NO_FAST = 1
TC_GUARD   = 1
TC_NO_LED  = 1

        * = BOOT_ORG
        jmp start
TCLIB_ORG = BOOT_ORG + 3
!source "tclib.s"

start:
        sei                     ; the initial loader leaves IRQs enabled, and
                                ; the KERNAL's handler would start the motor
        lda #0                  ; a black screen, not the loader's READY, while
        sta $d020               ; the launcher loads
        sta $d021
        lda #1                  ; white, for the stamp's message
        sta $0286
        lda #147
        jsr $ffd2
        lda #$2f
        sta $00
        lda #$37
        sta $01
        jsr tc_init
        jsr tc_cmdmode
        bcs fail
        jsr stamp
        jsr journals
go:     ;; the locator: the launcher's flash address (3 bytes) and length (2)
        lda #<LAUNCHER_LOC
        sta tc_addr
        lda #>LAUNCHER_LOC
        sta tc_addr+1
        lda #^LAUNCHER_LOC
        sta tc_addr+2
        lda #<loc
        sta tc_dest
        lda #>loc
        sta tc_dest+1
        lda #5
        sta tc_len
        lda #0
        sta tc_len+1
        jsr tc_read
        ;; the launcher, its PRG header left out: it loads to FONT_ORG
        ldx #2
-       lda loc,x
        sta tc_addr,x
        dex
        bpl -
        inc tc_addr             ; + 2 (the PRG header): the PRG never starts
        inc tc_addr             ; at a page's last byte (it is page aligned)
        lda loc+3
        sec
        sbc #2
        sta tc_len
        lda loc+4
        sbc #0
        sta tc_len+1
        lda #<FONT_ORG
        sta tc_dest
        lda #>FONT_ORG
        sta tc_dest+1
        jsr tc_read
        jmp MENU_ORG

fail:   inc $d020               ; no command mode: nothing to start
        jmp fail

;;; ---- the stamp ------------------------------------------------------
stamp:
        lda #<SETTINGS
        sta tc_addr
        lda #>SETTINGS
        sta tc_addr+1
        lda #^SETTINGS
        sta tc_addr+2
        lda #16
        jsr read_buf
        ldx #3
-       lda buf,x
        cmp magic,x
        bne wrong
        dex
        bpl -
        lda buf+SET_LAYOUT
        cmp #LAYOUT
        bne wrong
        rts
wrong:  ldx #0
-       lda wrong_text,x
        beq +
        jsr $ffd2
        inx
        bne -
+
halt:   jmp halt                ; nothing more: a power cycle after flashing

magic:  !text "UCFG"
wrong_text:
        !pet 147, 13, "the saves on this cart are laid out", 13
        !pet "for another build of the collection.", 13, 13
        !pet "flash this build's full .tcrt image", 13
        !pet "with write tcrt (its saves are then", 13
        !pet "empty) -- or the build that made them", 13
        !pet "again, to export them first.", 13, 0

;;; ---- the journals ---------------------------------------------------
journals:
        ldx #0
-       stx jn_i
        jsr jn_one
        ldx jn_i
        inx
        cpx #JOURNALS
        bne -
        rts

;;; journal jn_i: nothing (no header), or its save copied into the slot the
;;; header names; then (or for a header that names no slot) erased
jn_one:
        jsr jn_at
        lda #4
        jsr read_buf
        lda buf                 ; no header begun: nothing to do (an unfinished
        and buf+1               ; copy without one leaves the slot as it was,
        cmp #$ff                ; and the next save erases it)
        beq jn_rts
        lda buf                 ; begun and not whole: erased
        cmp #"J"
        bne jn_erase
        lda buf+1
        cmp #"N"
        bne jn_erase
        lda buf+2
        sta home_mid
        lda buf+3
        sta home_hi
        ;; the slot: block aligned, in the save region, below the journal
        ldx jn_i
        lda home_mid
        and #$0f
        bne jn_erase
        lda home_mid
        cmp jn_lo_mid,x
        lda home_hi
        sbc jn_lo_hi,x
        bcc jn_erase
        lda home_mid
        cmp jn_mid,x
        lda home_hi
        sbc jn_hi,x
        bcs jn_erase
        jsr jn_copy
jn_erase:
        jsr jn_at
        jmp tc_erase_block
jn_rts: rts

;;; tc_addr <- journal jn_i's first page
jn_at:  ldx jn_i
        lda #0
        sta tc_addr
        lda jn_mid,x
        sta tc_addr+1
        lda jn_hi,x
        sta tc_addr+2
        rts

;;; erase the slot's blocks, then copy the journal's pages 1.. into its pages 0..
jn_copy:
        lda jn_blocks,x
        sta jn_n
        lda home_mid
        sta jn_page
-       lda jn_page
        sta tc_addr+1
        lda home_hi
        sta tc_addr+2
        jsr tc_erase_block
        lda jn_page
        clc
        adc #$10
        sta jn_page
        dec jn_n
        bne -
        ldx jn_i
        lda jn_blocks,x
        asl
        asl
        asl
        asl
        sta jn_n                ; pages in the journal
        lda #1
        sta jn_page
jn_page_loop:
        jsr jn_at
        lda tc_addr+1
        clc
        adc jn_page
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       lda #0
        jsr read_buf            ; 256 bytes
        ldy #0                  ; an erased page needs no writing
-       lda buf,y
        cmp #$ff
        bne +
        iny
        bne -
        beq jn_copied
+       ldx jn_page             ; the slot's page jn_page - 1
        dex
        txa
        clc
        adc home_mid
        sta tc_addr+1
        lda home_hi
        adc #0
        sta tc_addr+2
        lda #<buf
        sta tc_dest
        lda #>buf
        sta tc_dest+1
        lda #0
        sta tc_len
        lda #1
        sta tc_len+1
        jsr tc_write
jn_copied:
        inc jn_page
        lda jn_page
        cmp jn_n
        bne jn_page_loop
        rts

;;; tc_addr's A bytes (0: 256) into buf
read_buf:
        sta tc_len
        lda #0
        sta tc_addr
        sta tc_len+1
        lda tc_len
        bne +
        inc tc_len+1
+       lda #<buf
        sta tc_dest
        lda #>buf
        sta tc_dest+1
        jmp tc_read

!source "boot_tab.s"

jn_i:      !byte 0
jn_n:      !byte 0
jn_page:   !byte 0
home_mid:  !byte 0
home_hi:   !byte 0
loc:    !fill 5, 0
boot_end:
!if boot_end - BOOT_ORG + 2 > BOOT_LEN {
        !error "boot.s is ", boot_end - BOOT_ORG + 2, " bytes with its header; the loadinfo loads ", BOOT_LEN
}
