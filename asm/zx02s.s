;;; zx02s.s -- zx02 decoder that pulls its input from a tapecart stream.
;;;
;;; Upstream zx02 (external/zx02/6502/zx02-optim.asm, MIT, Einar Saukas and
;;; DMSC; see NOTICE.md) reads its input through (zp),y.  This is a streaming
;;; variant: the three input reads become `jsr zx_getbyte`, so a unit
;;; decodes straight out of flash with no staging buffer.  Format: plain `zx02 <in> <out>`,
;;; no -b / -1 / -e / -s.
;;;
;;; Contract with the caller:
;;;   - the stream is already open (tc_stream_open) and is closed afterwards
;;;     by the caller (tc_stream_close drains anything left);
;;;   - zx_dst holds the destination; the stream carries its own end marker;
;;;   - zx_getbyte returns the next byte in A and preserves X, Y and the
;;;     carry -- tc_stream_byte does all three (php/plp around tc_getbyte).
;;;
;;; Zero page: only the two pointers used as (zp),y have to live there.  They
;;; are saved on entry and restored on exit, so the host
;;; game never sees them change -- and interrupts are off for the whole
;;; decode (tc_stream_open's tc_enter), so its IRQ handler never sees them
;;; either.  The bit buffer and the offset high byte are plain operands and
;;; live here instead.
;;;
;;; Define before !source: ZX_ZP (4 zero-page bytes, any), zx_getbyte.

ZX0_dst = ZX_ZP                 ; output pointer, (zp),y
pntr    = ZX_ZP+2               ; match source pointer, (zp),y

zx_unpack:
        ldx #3
-       lda ZX_ZP,x
        sta zx_zpsave,x
        dex
        bpl -
        lda zx_dst
        sta ZX0_dst
        lda zx_dst+1
        sta ZX0_dst+1
        lda #$80
        sta bitr
        lda #$ff                ; last offset = 1
        sta pntr
        ldy #$00
        sty offset_hi
        ldx #$00

decode_literal:
        inx
        jsr get_elias
cop0:   jsr zx_getbyte
        sta (ZX0_dst),y
        inc ZX0_dst
        bne +
        inc ZX0_dst+1
+       dex
        bne cop0
        asl bitr
        bcs dzx0s_new_offset

        inx
        jsr get_elias
dzx0s_copy:
        lda ZX0_dst+1
        sbc offset_hi           ; C=0 from get_elias: dst - offset - 1 + pntr
        sta pntr+1
cop1:   ldy ZX0_dst
        lda (pntr),y
        ldy #$00
        sta (ZX0_dst),y
        inc ZX0_dst
        bne +
        inc ZX0_dst+1
        inc pntr+1
+       dex
        bne cop1
        asl bitr
        bcc decode_literal

dzx0s_new_offset:
        inx
        jsr get_elias
        beq zx_exit             ; the end marker
        dex
        txa
        lsr
        sta offset_hi
        jsr zx_getbyte          ; carry from the lsr survives the call
        ror
        eor #$ff
        sta pntr
        ldx #$01
        jsr elias_skip1
        inx
        bcc dzx0s_copy

elias_get:
        asl bitr
        rol
        tax
get_elias:
        asl bitr
        bne elias_skip1
        jsr zx_getbyte          ; carry (the bit shifted out) survives
        rol
        sta bitr
elias_skip1:
        txa
        bcs elias_get
        rts

zx_exit:
        ldx #3
-       lda zx_zpsave,x
        sta ZX_ZP,x
        dex
        bpl -
        rts

zx_dst:     !word 0
offset_hi:  !byte 0
bitr:       !byte 0
zx_zpsave:  !fill 4, 0
