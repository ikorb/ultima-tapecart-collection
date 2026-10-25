;;; zxdecr.s -- zx02 decoding straight from tapecart flash, for Ultima 1-3
;;; and the menu.
;;;
;;; The decoder is zx02a.s (no zero page at all, so nothing of the host's is
;;; touched and interrupts may stay on); it pulls its input through tclib's
;;; tc_stream_byte, which keeps X, Y and the carry as zx02a needs, and writes
;;; wherever the caller asked.  Format: plain `zx02` (zx.py), nothing else.
;;;
;;; Two entries, because the games' tables differ:
;;;   zxd_unpack        tc_addr = the stream, tc_len = its length, tc_dest =
;;;                     where it goes (Ultima 1's and 2's tables have a
;;;                     length field)
;;;   zxd_unpack_sized  the same, but the blob starts with its own 16-bit
;;;                     length (Ultima 3's catalog entry has a block count,
;;;                     not a length; the menu's segments are shared with it)
;;;

zx_getbyte = tc_stream_byte

zxd_unpack:
        lda tc_dest
        sta zx_put+1
        lda tc_dest+1
        sta zx_put+2
        jsr tc_stream_open
        cld                     ; zx_copy subtracts
        jsr zx_unpack
        jmp tc_stream_close

;;; Enter with tc_addr on the blob (page aligned) and tc_dest on the
;;; destination.  Two bytes read up front cost about a millisecond; opening
;;; the stream long and draining the slack would cost far more at 1 bit.
zxd_unpack_sized:
        lda tc_dest             ; tc_read wants tc_dest as its target, so
        sta zxd_dest            ; park the real destination for a moment
        lda tc_dest+1
        sta zxd_dest+1
        lda #<zxd_len
        sta tc_dest
        lda #>zxd_len
        sta tc_dest+1
        lda #$02
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_read
        lda #$02                ; units are page aligned: stepping past the
        sta tc_addr             ; two length bytes cannot carry
        lda zxd_len
        sta tc_len
        lda zxd_len+1
        sta tc_len+1
        lda zxd_dest
        sta tc_dest
        lda zxd_dest+1
        sta tc_dest+1
        jmp zxd_unpack

!source "zx02a.s"

zxd_len:  !byte 0, 0
zxd_dest: !byte 0, 0
