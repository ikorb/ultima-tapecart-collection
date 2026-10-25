;;; init_u5.s -- Ultima 5 machine setup, run by the menu after loading.
;;;
;;; U5's first stage is `meow` ($032C, 49 bytes, loaded over the KERNAL vector
;;; table) whose only job is to LOAD `xyzzy` and jump to it.  `xyzzy` ($2000)
;;; is preloaded as a segment here, with its drive-dependent middle patched
;;; out, so all this stub does is the machine setup that has to happen before
;;; the driver can talk to the cart, and then hand over at $2000.
;;;
;;; $01 = $26, not the $06 xyzzy uses: bit 5 is the tape motor, and clearing
;;; it drops the cart back to streaming mode.  build.py rewrites the six
;;; immediate operands in the game that would otherwise clear it.

        * = $0200

        sei
        lda #$2f
        sta $00
        lda #$26                ; BASIC out, KERNAL in, I/O in; motor off
        sta $01

        lda #$00                ; drop the keypress that chose this game --
        sta $c6                 ; xyzzy reads $C5 to offer its drive menu

        ;; The kernal IRQ handler starts the tape motor unless $C0 is
        ;; non-zero, and a motor pulse drops the cart out of command mode.
        ;; tclib re-arms this on every exit; set it before the first CLI.
        lda #$01
        sta $c0

        ldx #3                  ; (u5_dirpage, u5_dircount: build.py filled them in)
-       lda u5_dirpage,x
        sta dir_page,x
        dex
        bpl -
        jsr tc_init             ; the driver's port values (asm/tcinit.s, below)
        ;; point the cart at the directory: it keeps the parameters until
        ;; they are set again (u5_dirinit in the C128 build)
        jsr tc_enter
        ldy #0                  ; (Y: tc_sendbyte may not keep X)
-       lda dir_args,y
        jsr tc_sendbyte
        iny
        cpy #8
        bne -
        jsr tc_leave

        jmp $2000               ; xyzzy

dir_args:
        !byte CMD_DIR_SETPARAMS
        !byte $00               ; the directory is page aligned
dir_page:
        !byte 0, 0, 0, 0        ; u5_dirpage and u5_dircount, copied in first
        !byte DIR_NAMELEN, DIR_DATALEN

!source "u5_tcinit.s"           ; the driver's symbols (build.py, tcsyms.py)
!source "tcinit.s"
init_end:
!if init_end > $0277 {
        !error "the init stub reaches the keyboard buffer at $0277: ", init_end
}
