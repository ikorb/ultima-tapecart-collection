;;; page_u6t.s -- Ultima VI: the Avatar from Ultima IV or V (T on the page;
;;; included by page.s).
;;;
;;; The PC's Ultima VI takes the Avatar from a saved game of IV or V at
;;; character creation; the C64's never could.  Here it goes into a new
;;; game -- one whose Avatar is as character creation left it, level 3 with
;;; 370 experience (i_u6 sets u6_new) -- by the PC's rules: experience / 10,
;;; the last digit dropped; strength, dexterity and intelligence halved from
;;; IV (its limit is 50, VI's 30), kept from V (whose limit is 30).  Never
;;; below what creation gives, though: experience at least 370, so the
;;; level -- by the shrines' thresholds, 100 200 400 800 -- is 3, 4 or 5.
;;; Hit points 30 a level and magic points twice the intelligence, as
;;; creation and the shrines set them.  The name and sex stay as chosen in
;;; creation (the PC asks for them again); the C64 has no portrait choice.
;;;
;;; The page only works it out.  It goes to init_u6.s as pokes (U6_XF,
;;; eight bytes in the order below), and the boot writes it into the newest
;;; save area after its log checks, so Journey Onward starts with it.
;;;
;;; Ultima IV (block 273; record 0 is the Avatar): +$13-$15 STR DEX INT,
;;; +$1A the level (the maximum hit points' high byte), +$1C/$1D the
;;; experience; all BCD, high byte first.  Ultima V (ROSTER, record 0 at
;;; +$80): +4-6 STR DEX INT, +$C/$D the experience (BCD, high byte first),
;;; +$E the level (binary).

x6_transfer:
        lda #$93
        jsr CHROUT
        jsr pr
        !pet 13," Transfer the Avatar into Ultima VI:",13,13,0
        lda #$00
        sta t_have
        ;; ---- Ultima IV --------------------------------------------------
        lda #<U4_ZP
        ldx #>U4_ZP
        ldy #^U4_ZP
        jsr fread1
        lda BUF+$0f             ; the party's size: 0 = no game
        beq t_no4
        cmp #$09
        bcs t_no4
        lda #<U4_ROSTER
        ldx #>U4_ROSTER
        ldy #^U4_ROSTER
        jsr fread1
        ldx #$00                ; U4's column in the t_ tables
        lda BUF+$13
        jsr t_attr4
        sta t_str
        lda BUF+$14
        jsr t_attr4
        sta t_dex
        lda BUF+$15
        jsr t_attr4
        sta t_int
        lda BUF+$1c
        ldy BUF+$1d
        jsr t_xp10
        jsr pr
        !pet "   4  ",0
        lda #<BUF
        sta ptr
        lda #>BUF
        sta ptr+1
        lda #15
        jsr prname
        lda BUF+$1a
        jsr bcd2bin
        jsr t_level
        lda t_have
        ora #$01
        sta t_have
t_no4:
        ;; ---- Ultima V ---------------------------------------------------
        lda #<U5_ROSTER
        ldx #>U5_ROSTER
        ldy #^U5_ROSTER
        jsr fread2
        jsr magic_ok
        bne t_no5
        lda BUF+$100            ; no name: no character yet
        beq t_no5
        ldx #$01
        lda BUF+$184
        jsr t_attr5
        sta t_str+1
        lda BUF+$185
        jsr t_attr5
        sta t_dex+1
        lda BUF+$186
        jsr t_attr5
        sta t_int+1
        lda BUF+$18c
        ldy BUF+$18d
        jsr t_xp10
        jsr pr
        !pet "   5  ",0
        lda #<(BUF+$100)
        sta ptr
        lda #>(BUF+$100)
        sta ptr+1
        lda #$88                ; 8 letters, the last with bit 7 clear
        jsr prname
        lda BUF+$18e
        jsr t_level
        lda t_have
        ora #$02
        sta t_have
t_no5:
        lda t_have
        bne +
        jsr pr
        !pet "   There is no saved game of",13
        !pet "   Ultima IV or Ultima V.",13,0
        jsr getkey
        jmp redraw
+       jsr pr
        !pet 13," Which one? (4/5) ",0
        jsr getkey
        pha                     ; shown, then a blank line
        jsr CHROUT
        lda #13
        jsr CHROUT
        pla
        ldx #$00
        cmp #"4"
        beq +
        inx
        cmp #"5"
        bne t_back
+       txa                     ; the bit for that game
        clc
        adc #$01
        and t_have
        bne t_pick
t_back: jmp redraw

        ;; ---- what it becomes ---------------------------------------------
t_pick: lda t_str,x
        sta t_vals+1
        lda t_dex,x
        sta t_vals+2
        lda t_int,x
        sta t_vals+3
        asl                     ; magic points: twice the intelligence
        sta t_vals+5
        lda t_xl,x
        sta t_vals+6
        lda t_xh,x
        sta t_vals+7
        lda t_vals+7            ; experience: at least creation's 370
        cmp #>370
        bcc t_min
        bne +
        lda t_vals+6
        cmp #<370
        bcs +
t_min:  lda #<370
        sta t_vals+6
        lda #>370
        sta t_vals+7
+       ldx #$03                ; the level: 3, then one for each of the
        ldy #$01                ; thresholds 400 and 800 reached (the
-       lda t_vals+6            ; experience is 999 at most)
        cmp t_thr_lo,y
        lda t_vals+7
        sbc t_thr_hi,y
        bcc +
        inx
        dey
        bpl -
+       stx t_vals
        lda #$00                ; hit points: 30 a level
        clc
-       adc #30
        dex
        bne -
        sta t_vals+4

        jsr pr
        !pet 13," In Ultima VI:",13,13,"   Strength    ",0
        lda t_vals+1
        jsr t_num
        jsr pr
        !pet "   Dexterity   ",0
        lda t_vals+2
        jsr t_num
        jsr pr
        !pet "   Intellect   ",0
        lda t_vals+3
        jsr t_num
        jsr pr
        !pet "   Level       ",0
        lda t_vals
        jsr t_num
        jsr pr
        !pet "   Health      ",0
        lda t_vals+4
        jsr t_num
        jsr pr
        !pet "   Magic       ",0
        lda t_vals+5
        jsr t_num
        jsr pr
        !pet "   Experience  ",0
        lda t_vals+6
        ldx t_vals+7
        jsr prdec16
        jsr pr
        !pet 13,13," The name and sex stay as created.",13
        !pet " Journey onward with it? (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       lda #$01
        sta t_go
        jmp journey

;;; u6_new = 1 if the Avatar in S12/S13 (BUF, i_u6) is as creation left
;;; it: level 3 ($57BA) and 370 experience ($585B)
t_isnew:
        lda BUF+$ba
        cmp #$03
        bne +
        lda BUF+$15b
        cmp #<370
        bne +
        lda BUF+$15c
        cmp #>370
        bne +
        inc u6_new
+       rts

;;; A (0-255) as a number, then a new line
t_num:  ldx #$00
        jsr prdec16
        lda #13
        jmp CHROUT

;;; ", level " and A, a new line
t_level:
        pha
        jsr pr
        !pet " level ",0
        pla
        jmp t_num

;;; an attribute of Ultima IV (BCD, at most 50) or V (BCD, at most 30) in
;;; A, as Ultima VI's: halved from IV, then 1 to 30
t_attr4:
        jsr bcd2bin
        lsr
        jmp +
t_attr5:
        jsr bcd2bin
+       cmp #$00
        bne ++
        lda #$01
++      cmp #31
        bcc +
        lda #30
+       rts

;;; experience, BCD, high byte A and low byte Y, divided by ten (its last
;;; digit dropped) into t_xl/t_xh,x: high x 10 + low's high digit
t_xp10: sty t_tmp
        jsr bcd2bin
        sta t_xl,x              ; n
        lda #$00
        sta t_xh,x
        asl t_xl,x              ; 2n
        rol t_xh,x
        lda t_xl,x
        sta t_tmp2
        lda t_xh,x
        sta t_tmp2+1
        asl t_xl,x              ; 8n
        rol t_xh,x
        asl t_xl,x
        rol t_xh,x
        clc                     ; + 2n = 10n
        lda t_xl,x
        adc t_tmp2
        sta t_xl,x
        lda t_xh,x
        adc t_tmp2+1
        sta t_xh,x
        lda t_tmp               ; + the tens digit
        lsr
        lsr
        lsr
        lsr
        clc
        adc t_xl,x
        sta t_xl,x
        bcc +
        inc t_xh,x
+       rts

;;; A, two BCD digits, as binary
bcd2bin:
        pha
        and #$0f
        sta t_tmp2
        pla
        lsr
        lsr
        lsr
        lsr
        tay                     ; tens: x 10 = x 8 + x 2
        asl
        asl
        asl
        sta t_tmp2+1
        tya
        asl
        clc
        adc t_tmp2+1
        adc t_tmp2
        rts

;;; the transfer's pokes, if T asked for them (launch)
t_pokes:
        lda t_go
        beq +
        ldy #$00
-       tya
        clc
        adc #<U6_XF
        sta ptr
        lda #>U6_XF
        adc #$00
        sta ptr+1
        lda t_vals,y
        jsr add_poke            ; (keeps Y)
        iny
        cpy #$08
        bne -
+       rts

t_thr_lo: !byte <800, <400
t_thr_hi: !byte >800, >400
t_have:  !byte 0                ; bit 0: Ultima IV has an Avatar, bit 1: V
t_go:    !byte 0
t_str:   !fill 2, 0             ; per game: IV, V
t_dex:   !fill 2, 0
t_int:   !fill 2, 0
t_xl:    !fill 2, 0
t_xh:    !fill 2, 0
t_tmp:   !byte 0
t_tmp2:  !word 0
t_vals:  !fill 8, 0             ; level, STR, DEX, INT, HP, MP, experience (2)
