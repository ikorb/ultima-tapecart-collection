;;; eftc.s -- tclib for the EasyFlash launcher: Ultima VI's world to and from
;;; the tapecart, both carts plugged in.
;;;
;;; The launcher's tc_* names are eflib's (the EasyFlash); this is a second,
;;; separately assembled tclib with its own parameter block, which eflib
;;; switches to while el_dev says "the tapecart" (eflib.s, EFLIB_TC).  It is
;;; kept in the cart's data area and read to TCX_ORG when an export or import
;;; picks the tapecart (efpage.s tx_open), so bank 0's launcher image does
;;; not carry it.
;;;
;;; As the tapecart page's copy (asm/page.s): 1 bit, the screen on, the LED
;;; lit while data moves; and command mode entered here, since no menu held
;;; it -- at every open, so a cart that dropped back to streaming mode in
;;; between (a KERNAL IRQ with the motor) is simply taken back.
;;;
;;; The entries, three bytes apart from TCX_ORG:
;;;   +0  tx_open        $00/$01 as the KERNAL left them; C set: no tapecart
;;;   +3  tc_read        the rest: tclib's own (tclib.s), on its own block
;;;   +6  tc_write       (tc_addr, tc_len, tc_dest, adjacent; build.py puts
;;;   +9  tc_erase_block  its address in efpage_data.s as TCX_PARM)
;;;   +12 tc_enter
;;;   +15 tc_sendbyte
;;;   +18 tc_getbyte
;;;   +21 tc_leave

TC_NO_FAST   = 1
TC_NO_STREAM = 1

        * = TCX_ORG
        jmp tx_open
        jmp tc_read
        jmp tc_write
        jmp tc_erase_block
        jmp tc_enter
        jmp tc_sendbyte
        jmp tc_getbyte
        jmp tc_leave

TCLIB_ORG = *
!source "tclib.s"

;;; tc_init from the KERNAL's port values, then command mode (interrupts
;;; left off, as tc_cmdmode leaves them)
tx_open:
        sei
        lda #$2f
        sta $00
        lda #$37
        sta $01
        jsr tc_init
        jmp tc_cmdmode

tcx_end:
