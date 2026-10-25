;;; menu.s -- Ultima Tapecart Collection game selector.
;;;
;;; This is what the tapecart's own initial loader fastloads and starts, so
;;; the cart is a standalone product: LOAD"",1,1 (or SHIFT+RUN/STOP) and pick
;;; a game.
;;;
;;; It is entirely game-agnostic.  Everything game-specific lives in flash:
;;;
;;;   $000000  game list   count, then 18 bytes per game (16-byte name,
;;;                        descriptor index, descriptor page)
;;;   $00xx00  descriptors one 256-byte page per game, at $000100 + n*256
;;;                        for the first six, at the top of the reserved
;;;                        area for Akalabeth (regions.desc_offset): entry
;;;                        address, segment count, then 7 bytes per segment
;;;                        (flash page, length, destination, flags)
;;;
;;; A game's place in the list is its key: 0 Akalabeth, 1-6 Ultima I-VI.
;;;
;;; A segment's flag bit 0 says it is stored zx02-crunched, with its own
;;; length in the first two bytes.  Ultima 3's EXOD is 22 KiB of intro and
;;; makes up a third of that game's data, so it is worth the 557 bytes the
;;; decruncher adds here.
;;;
;;; The descriptor's entry address points at that game's init stub, which is
;;; loaded as an ordinary segment -- so adding a game needs no change here.
;;;
;;; Picking a game first runs the launcher's page for it (asm/page.s: the
;;; saved game, the game's options, a reset, export and import).  The page
;;; and the launcher's font come in with the menu itself: the first stage
;;; loads one PRG from $4800 (ultima/build.py) -- font at $4800, page at
;;; $5000, this at $8700, then U6's REU line, the page's export tables and
;;; the page's second piece from $A000 -- so there is no load, and no blank
;;; screen, when a game is picked.  The page returns either "back to the
;;; list" or "launch", with a few bytes to poke once the game is loaded and
;;; before its init stub runs -- which is how an option reaches a game's
;;; driver without the menu knowing about it.
;;;

ptr  = $02
ptr2 = $04

;;; Lives at $8700.  It has to be clear of every segment every game loads,
;;; because it is still running the load loop while they land:
;;;   $0200-$0282  init stubs        $0800-$15da  U1
;;;   $2000-$23df  U5 (xyzzy)        $3000-$86ff  U3 (EXOD)
;;;   $6c00-$7dff  U5               $a100-$a92d  U4
;;;   $b000-$bf5f  U2, U3            $c000-$cfff  U2 (INTRO)
;;;   $0801-$7a2e  Akalabeth         $c000-$c8a6  its LIB
;;; That leaves $8700-$a0ff, and not much else.  Only the menu has to be
;;; there: what follows it in the PRG is the page's, done with by then.  It has moved twice already:
;;; from $C600 when Ultima 2 loaded INTRO over it, then from $2000 when
;;; Ultima 5 loaded xyzzy over it.  test_collection.py checks every segment
;;; of every game against this address now.
MENU_ORG    = $8700
TABLE_ADDR  = $000000
TABLE_SIZE  = 128
DESC_SIZE   = 64
NAME_LEN    = 16
RECORD_LEN  = 18

SEG_COMP    = %00000001         ; segment flag: stored crunched
PAGE_ORG    = $5000
POKES_MAX   = 12                ; the page's list (page.s POKES)
;;; The launcher's look: Ultima I's font (launcher.py), white on black, in
;;; VIC bank 1 (bank 0 shows the ROM font wherever $1000-$1FFF is): screen
;;; $4400, font $4800, the page after it.  All of it is overwritten by a
;;; game's segments, and the look is taken down before any is loaded.
SCREEN      = $4400
FONT        = $4800

CHROUT = $ffd2
WHITE  = 5                      ; two brightnesses, as the page's
GREY   = 155
PLOT   = $fff0
SCNKEY = $ff9f
GETIN  = $ffe4

        * = MENU_ORG

;;; The loader's call address is MENU_ORG itself, whatever the menu grows
;;; into.  An update image (ultima/build.py) rewrites the flash but not the
;;; cart's loadinfo, so the call address -- like the data length, which is
;;; the whole menu area -- has to stay the same from build to build.
        jmp start

TCLIB_ORG = MENU_ORG + 3
!source "tclib.s"
!source "zxdecr.s"

start:
        sei                     ; the initial loader leaves IRQs enabled, and
                                ; the kernal handler would start the motor
        lda #$2f
        sta $00
        lda #$37
        sta $01                 ; BASIC + KERNAL + I/O, motor bit set

        jsr tc_init
        jsr tc_cmdmode
        bcc +
        jmp no_cart
+
        ;; ---- read the game list ------------------------------------
        lda #<TABLE_ADDR
        sta tc_addr
        lda #>TABLE_ADDR
        sta tc_addr+1
        lda #^TABLE_ADDR
        sta tc_addr+2
        lda #TABLE_SIZE
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<table
        sta tc_dest
        lda #>table
        sta tc_dest+1
        jsr tc_read             ; 1-bit: no need to blank for 128 bytes

        jsr look_on             ; the font came with the menu

        ;; ---- draw the menu -----------------------------------------
menu_top:
        lda #$93                ; clear screen
        jsr CHROUT
        jsr draw_logo
        ldx #13                 ; the banner under it, two rows clear
        ldy #0
        clc
        jsr PLOT
        lda #<m_title
        ldy #>m_title
        jsr prtstr

        lda #$00
        sta index
draw_loop:
        lda index
        cmp table
        bcs draw_done
        lda #$0d
        jsr CHROUT
        lda #$20
        jsr CHROUT
        lda #WHITE              ; the key white, the name grey (page.s)
        jsr CHROUT
        lda index               ; "0.", "1.", ...
        clc
        adc #$30
        jsr CHROUT
        lda #GREY
        jsr CHROUT
        lda #$2e
        jsr CHROUT
        lda #$20
        jsr CHROUT

        jsr record_ptr          ; ptr -> this game's record
        ldy #$00
-       lda (ptr),y
        beq +
        jsr CHROUT
        iny
        cpy #NAME_LEN
        bne -
+       inc index
        jmp draw_loop
draw_done:                      ; seven games on rows 16-22, a blank row,
                                ; the prompt on row 24
        lda #<m_prompt
        ldy #>m_prompt
        jsr prtstr

        ;; ---- wait for a choice -------------------------------------
        ;; Interrupts are off, so the kernal is not scanning the keyboard
        ;; for us; drive SCNKEY by hand.
!ifdef MENU_AUTOKEY {
        ;; test builds pick a game without a keypress
        lda #MENU_AUTOKEY
        sta index
        jmp chosen
}
key_loop:
        jsr SCNKEY
        jsr GETIN
        beq key_loop
        sec
        sbc #$30                ; '0' -> 0
        bcc key_loop
        cmp table               ; past the last game?
        bcc +
!ifdef MENU_AUTOKEY {
        jmp key_loop
} else {
        cmp #7                  ; 7-9: Ultima VII to IX, which the page
        bcc key_loop            ; says are not here (page.s not_here:
        cmp #10                 ; A = $80 + the number, always back)
        bcs key_loop
        ora #$80                ; 7-9 -> $87-$89
        sta index
        jsr run_page
        jmp page_back
}
+       sta index
chosen:

        ;; ---- load the chosen game ----------------------------------
        jsr record_ptr
        ldy #NAME_LEN
        lda (ptr),y             ; descriptor index
        sta index
        iny
        lda (ptr),y             ; and the descriptor's flash page
        sta descpage
!ifndef MENU_AUTOKEY {
        jsr run_page            ; its page: back to the list, or on
        bcc +++
page_back:
        cmp table               ; another game's page (its list place)?
        bcs ++
        sta index
        jmp chosen
++      jmp menu_top
+++
}

        lda #$00
        sta tc_addr
        sta tc_addr+2
        lda descpage
        sta tc_addr+1
        lda #DESC_SIZE
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<desc
        sta tc_dest
        lda #>desc
        sta tc_dest+1
        jsr tc_read

        jsr look_off            ; the machine as the games expect it
        jsr tc_blank            ; fast reads need a quiet display

        lda desc+2
        sta segcount
        lda #$00
        sta segidx
        ;; Ultima V's xyzzy takes a $4C (JMP) at $C024 for the C128's
        ;; editor ROM, but on a C64 $C024 is RAM, and a reset leaves what the
        ;; last game had there: U5 then takes its C128 path and crashes.  A
        ;; known value first, before the segments (U1's and U6's land on it).
        sta $c024
seg_loop:
        lda segcount
        beq seg_done
        ldx segidx
        lda #$00
        sta tc_addr             ; segments are page aligned
        lda desc+3,x
        sta tc_addr+1
        lda desc+4,x
        sta tc_addr+2
        lda desc+5,x
        sta tc_len
        lda desc+6,x
        sta tc_len+1
        lda desc+7,x
        sta tc_dest
        lda desc+8,x
        sta tc_dest+1
        lda desc+9,x            ; flags: bit 0 = stored crunched
        and #SEG_COMP
        beq +
        jsr zxd_unpack_sized    ; the blob carries its own length
        jmp seg_next
+       jsr tc_read_fast
seg_next:
        lda segidx
        clc
        adc #$07
        sta segidx
        dec segcount
        jmp seg_loop
seg_done:
        jsr tc_unblank          ; the game's init stub sets up its own screen

        ldx #$00                ; the page's pokes, now that the game is in
        lda pokes
        sta segcount
-       lda segcount
        beq +
        lda pokes+1,x
        sta ptr
        lda pokes+2,x
        sta ptr+1
        lda pokes+3,x
        ldy #$00
        sta (ptr),y
        inx
        inx
        inx
        dec segcount
        jmp -
+

        lda #$0e                ; the KERNAL's colours (black until now, so
        sta $d020               ; the loads show a black screen)
        lda #$06
        sta $d021
        lda desc+1
        sta go+2
        lda desc+0
        sta go+1
go:
        jmp $ffff               ; patched to the game's init stub

;;; U1's font, white on black, in VIC bank 1; Shift+C= does not switch the
;;; character set (the KERNAL would flip $D018 onto the page's data)
look_on:
        lda #$00
        sta $d020
        sta $d021
        lda #$01
        sta $0286               ; CHROUT's colour
        lda #$80
        sta $0291               ; no Shift+C=
        lda $dd00               ; bank 1; $DD00's other bits are the serial
        and #%11111100          ; bus's, left alone
        ora #%00000010
        sta $dd00
        lda #((SCREEN & $3c00) >> 6) | ((FONT & $3800) >> 10)
        sta $d018
        lda #>SCREEN
        sta $0288               ; where CHROUT prints
        rts

;;; and back: bank 0, screen $0400 blank, the ROM font, the KERNAL's text
;;; colour and Shift+C=.  The border stays black through the loads.
look_off:
        ldx #$00                ; no sprites, as after a reset
        stx $d015
        stx $d010
        stx $d017
        stx $d01b
        stx $d01d
        lda $dd00
        ora #%00000011
        sta $dd00
        lda #$15
        sta $d018
        lda #$04
        sta $0288
        lda #$00
        sta $0291
        lda #$0e
        sta $0286
        ldx #$00
-       lda #$20
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        lda #$0e
        sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $db00,x
        inx
        bne -
        rts

;;; The logo (logo.py, from art/logo.txt): its characters, which are in the
;;; font, in rows 0-10 of the screen, each cell in its own colour.
draw_logo:
        lda #<logo_scr
        sta dl_s+1
        lda #>logo_scr
        sta dl_s+2
        lda #<logo_col
        sta dl_c+1
        lda #>logo_col
        sta dl_c+2
        lda #<(SCREEN + LOGO_LEFT)      ; screen and colour RAM are both
        sta ptr                         ; page aligned
        sta ptr2
        lda #>(SCREEN + LOGO_LEFT)
        sta ptr+1
        lda #>($d800 + LOGO_LEFT)
        sta ptr2+1
        ldx #LOGO_H
dl_row: ldy #LOGO_W - 1
dl_s:   lda $ffff,y
        sta (ptr),y
dl_c:   lda $ffff,y
        sta (ptr2),y
        dey
        bpl dl_s
        lda dl_s+1
        clc
        adc #LOGO_W
        sta dl_s+1
        bcc +
        inc dl_s+2
+       lda dl_c+1
        clc
        adc #LOGO_W
        sta dl_c+1
        bcc +
        inc dl_c+2
+       lda ptr
        clc
        adc #40
        sta ptr
        sta ptr2
        bcc +
        inc ptr+1
        inc ptr2+1
+       dex
        bne dl_row
        rts

;;; ptr -> the record for game `index`
record_ptr:
        lda #<(table+1)
        sta ptr
        lda #>(table+1)
        sta ptr+1
        ldx index
        beq rp_done
-       lda ptr
        clc
        adc #RECORD_LEN
        sta ptr
        bcc +
        inc ptr+1
+       dex
        bne -
rp_done:
        rts

;;; The page for game `index`, whose record ptr points at.  C set: back.
;;; BASIC is banked out while it runs: its second piece is at $A000.
run_page:
        lda #$36                ; KERNAL and I/O, motor bit set
        sta $01
        lda index
        ldx ptr
        ldy ptr+1
        jsr PAGE_ORG
        pha
        lda #$37                ; the menu's (and the games' start's) again
        sta $01
        pla
        bcs +
        stx ptr2                ; launch: keep its pokes, the page is about
        sty ptr2+1              ; to be loaded over
        ldy #$00
        lda (ptr2),y
        cmp #POKES_MAX + 1
        bcc ++
        lda #POKES_MAX
++      sta pokes
        asl
        adc pokes
        tay
-       lda (ptr2),y
        sta pokes,y
        dey
        bne -
        clc
+       rts

no_cart:
        lda #$02
        sta $d020
        lda #<m_nocart
        ldy #>m_nocart
        jsr prtstr
-       jmp -

prtstr:
        sta ptr2
        sty ptr2+1
        ldy #$00
-       lda (ptr2),y
        beq +
        jsr CHROUT
        iny
        bne -
+       rts

;;; Mixed case in the source: acme's !pet makes a-z $41-$5A and A-Z $C1-$DA,
;;; which is what the lower-case layout of the launcher's font shows as
;;; such.  banner.s is generated into build/ by the builder: the version
;;; from the Makefile -- and a debug build says so, in red, on the second
;;; line (ultima/build.py banner_fragment).  acme's -D takes numbers only, which
;;; is why this is an include and not a command-line define.
m_title:  !source "banner.s"        ; the version, and the second line
          !pet 13,0
m_prompt: !pet GREY,13,13,"    Select a game: ",0
m_nocart: !pet 13,"no tapecart found.",13,0

index:    !byte 0
descpage: !byte 0
pokes:    !fill 1 + 3 * POKES_MAX, 0
segcount: !byte 0
segidx:   !byte 0
table:    !fill TABLE_SIZE, 0
desc:     !fill DESC_SIZE, 0
!source "logo.s"
menu_end:
