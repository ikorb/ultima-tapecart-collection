;;; launch128.s -- Ultima V from the tapecart, in C128 mode.
;;;
;;; The tapecart cannot start a C128 in native mode (its autostart is the
;;; C64's tape load), but its command mode works for any program that talks
;;; to it.  So this goes on a disk -- the launcher's page writes it -- and
;;; the player types DLOAD"ULTIMA V 128" and RUN (or RUN"ULTIMA V 128"),
;;; with the cart in the tape port.  It enters command mode, loads what
;;; Ultima V's C128 boot loaded from disk 1A, from the cart, and starts
;;; xyzzy as the C128 boot sector did:
;;;
;;;   bank 1  `m` at $7200 (the music; the original copied it up from bank
;;;           0) and sub128.s at $E000 (the overlay cache)
;;;   bank 0  c128far.s at $0200, xyzzy, temp.subs and the driver at $7700
;;;           -- the C128 builds of the last two (u5drv.s with U5_C128)
;;;
;;; The saved game is the C64's, in the same flash: Journey Onward on either
;;; machine goes on from the other's save.  The launcher's options for
;;; Ultima V come from its settings page, as the menu pokes them.
;;;
;;; A BASIC program: DLOAD puts it wherever BASIC's text starts, so the SYS
;;; reads that from TXTTAB ($2D/$2E) and the first thing the code does is
;;; copy the rest of itself to $1300, clear of everything it loads ($1C01
;;; on is xyzzy's and the game's).  It has to run in bank 0 below $4000,
;;; as it does after a reset: with BASIC moved up by GRAPHIC it would sit
;;; under the BASIC ROM.

!source "c128.inc"

TXTTAB  = $2d
ORG     = $1300                 ; the C128's free RAM for machine code
CHROUT  = $ffd2
ptr     = $fb                   ; free for machine code in C128 mode
ptr2    = $fd

SEG_ZX  = %00000001             ; a zx02 stream (plain: its length is the
                                ; stream's)
SEG_B1  = %00000010             ; lands in RAM bank 1
SEG_ON  = %10000000             ; set in every entry; a zero ends the table

        * = $1c01
        !word bas_end           ; (DLOAD relinks it anyway)
        !word 10
        !byte $9e               ; SYS
        !byte $c2               ; PEEK
        !text "(45)"
        !byte $aa               ; +
        !text "256"
        !byte $ac               ; *
        !byte $c2               ; PEEK
        !text "(46)"
        !byte $aa               ; +
        !text "26"
        !byte 0
bas_end:
        !word 0
!if * - $1c01 != 26 {
        !error "the SYS offset is ", * - $1c01, ", not 26"
}
;;; position independent until the copy is done: TXTTAB + 26 is here
        lda TXTTAB
        clc
        adc #<(body - $1c01)
        sta ptr
        lda TXTTAB+1
        adc #>(body - $1c01)
        sta ptr+1
        lda #<ORG
        sta ptr2
        lda #>ORG
        sta ptr2+1
        ldx #>(body_end - body + $ff)
        ldy #$00
-       lda (ptr),y
        sta (ptr2),y
        iny
        bne -
        inc ptr+1
        inc ptr2+1
        dex
        bne -
        jmp ORG

body:
!pseudopc ORG {
        jmp start

TC_NO_FAST  = 1
TC_KEEP_01  = %11000111         ; a C128's $01 bits 0-2 are the colour RAM
TC_IO_01    = %00000000         ; banks and the VIC's charset, not banking
TC_NO_ERASE = 1
TC_NO_WRITE = 1
TCLIB_ORG = *
!source "tclib.s"
!source "zxdecr.s"
!source "launch128_data.s"      ; build.py: C128_DESC, SETTINGS_AT -- both
                                ; fixed addresses (regions.py), so a disk
                                ; written once works with any later build

;;; The descriptor page at C128_DESC (ultima/games/u5/build.py c128_desc):
D_MAGIC  = 0                    ; "U5C128", then version 1
D_INIT   = 7                    ; the driver's tc_init
D_DIR    = 9                    ; its u5_dirinit
D_OPTS   = 11                   ; its options byte
D_CAPS   = 13                   ; the options it has
D_OPTAT  = 14                   ; U5's byte in the settings page
D_ENTRY  = 15                   ; xyzzy's start
D_SEGS   = 17                   ; 8 bytes a segment, a zero flags byte ends them
D_VERSION = 1                   ; (build.py C128_DESC_VERSION)

start:
        sei
        lda #MMU_IO             ; RAM to $BFFF, I/O, KERNAL (BASIC's bank 15
        sta $ff00               ; has its ROM over $4000-$BFFF)
        lda #$00
        sta $d030               ; 1 MHz: the VIC shows nothing at 2
        lda #147                ; a clear screen, the lower case set --
        jsr CHROUT              ; which the editor would only hand the VIC
        lda #14                 ; in its IRQ, off here: its shadow ($0A2C)
        jsr CHROUT              ; straight to $D018
        lda $0a2c
        sta $d018
        lda #<m_hello
        ldy #>m_hello
        jsr prstr
        lda #$2f
        sta $00
        lda $01
        ora #%00100000          ; motor off
        sta $01
        jsr tc_init
        jsr tc_cmdmode
        bcc +
        lda #<m_nocart
        ldy #>m_nocart
        jmp fail
+
        ;; ---- what to load, from the cart itself ---------------------
        lda #<C128_DESC
        sta tc_addr
        lda #>C128_DESC
        sta tc_addr+1
        lda #^C128_DESC
        sta tc_addr+2
        lda #<desc
        sta tc_dest
        lda #>desc
        sta tc_dest+1
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        jsr tc_read
        ldx #6
-       lda desc+D_MAGIC,x
        cmp magic5,x
        bne +
        dex
        bpl -
        bmi seg0
+       lda #<m_nogame
        ldy #>m_nogame
        jmp fail

        ;; ---- the segments ------------------------------------------
seg0:   ldx #D_SEGS
seg:    stx segi
        lda desc,x
        bne +
        jmp segs_done
+       sta segf
        lda desc+1,x
        sta tc_addr
        lda desc+2,x
        sta tc_addr+1
        lda desc+3,x
        sta tc_addr+2
        lda desc+4,x
        sta tc_len
        lda desc+5,x
        sta tc_len+1
        lda desc+6,x
        sta tc_dest
        lda desc+7,x
        sta tc_dest+1
        lda segf
        and #SEG_B1
        beq +
        lda #%00000110          ; bottom 8 KiB common: this code, its
        sta $d506               ; variables and the stack stay in view
        lda #$7f                ; bank 1, all RAM
        bne ++
+       lda #MMU_B0             ; bank 0, all RAM
++      sta $ff00
        lda segf
        and #SEG_ZX
        beq +
        jsr zxd_unpack
        jmp ++
+       jsr tc_read
++      lda #MMU_IO
        sta $ff00
        lda #%00000100          ; the C128's own: 1 KiB common, at the
        sta $d506               ; bottom -- what `m` and sub128.s expect
        lda segi
        clc
        adc #8
        tax
        jmp seg

segs_done:
        ;; ---- the options, as the menu would poke them ------------------
        lda #<SETTINGS_AT
        sta tc_addr
        lda #>SETTINGS_AT
        sta tc_addr+1
        lda #^SETTINGS_AT
        sta tc_addr+2
        lda #<sbuf
        sta tc_dest
        lda #>sbuf
        sta tc_dest+1
        lda #16
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_read
        lda desc+D_OPTS
        sta opts+1
        lda desc+D_OPTS+1
        sta opts+2
        ldx #$03
-       lda sbuf,x
        cmp magic,x
        bne +
        dex
        bpl -
        ldx desc+D_OPTAT        ; "UCFG", then a byte per game
        lda sbuf,x
        and desc+D_CAPS
        !byte $2c               ; (BIT abs: over the LDA)
+       lda #$00                ; an erased page: all off
opts:   sta $ffff

        ;; ---- then as init_u5.s does, and into xyzzy ------------------
        lda #$2f
        sta $00
        lda #$26                ; the C64 banking xyzzy sets, motor off
        sta $01
        lda #$01
        sta $c0                 ; the KERNAL IRQ's tape interlock
        jsr drv_init
        jsr drv_dir
        lda #MMU_IO
        sta $ff00
        cli
        jmp (desc+D_ENTRY)
drv_init:
        jmp (desc+D_INIT)
drv_dir:
        jmp (desc+D_DIR)

;;; A/Y: a message; then back to BASIC as it was
fail:   jsr prstr
        lda #$00
        sta $ff00
        cli
        rts

PLOT    = $fff0
;;; A/Y: a message -- lines of row, column, text, 0; a row of $FF ends it
prstr:  sta ptr
        sty ptr+1
pr_line:
        ldy #$00
        lda (ptr),y
        bmi pr_done
        tax
        iny
        lda (ptr),y
        tay
        clc
        jsr PLOT                ; X = row, Y = column
        ldy #$02
-       lda (ptr),y
        beq +
        jsr CHROUT
        iny
        bne -
+       iny                     ; past the NUL, onto the next line
        tya
        clc
        adc ptr
        sta ptr
        bcc pr_line
        inc ptr+1
        bne pr_line
pr_done:
        rts

m_hello:                        ; (centred on the 40 columns)
        !byte 11, 7
        !pet "Ultima V from the tapecart", 0
        !byte $ff
m_nocart:
        !byte 13, 5
        !pet "No tapecart in the tape port.", 0
        !byte 15, 0, 0
        !byte $ff
m_nogame:
        !byte 13, 3
        !pet "This tapecart has no Ultima V for", 0
        !byte 14, 3
        !pet "the C128, or a different version.", 0
        !byte 16, 3
        !pet "Write the launcher again from the", 0
        !byte 17, 8
        !pet "Ultima V page on a C64.", 0
        !byte 19, 0, 0
        !byte $ff
magic:  !text "UCFG"
magic5: !text "U5C128"
        !byte D_VERSION
segi:   !byte 0
segf:   !byte 0
launch_end:
desc    = launch_end            ; buffers past the end: not on the disk
sbuf    = desc + 256
}
body_end:
!if sbuf + 16 > $1c00 {
        !error "the launcher runs past $1BFF: ", launch_end
}
!if sbuf + 16 > $2000 {
        !error "the launcher leaves the bottom 8 KiB, which a load into bank 1 needs"
}
