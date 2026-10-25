;;; page_text.s -- the page's names and numbers: a game's name in the
;;; launcher's characters, decimal and BCD numbers.  Included by page.s, and
;;; by the EasyFlash launcher (ultima/ef/efpage.s) for Ultima VI's party.  The
;;; includer has ptr, CHROUT and the variables nmode, nmax, ncol, nch, num
;;; (2), bcd (3), lz, npos and nwid (0).

;;; The name at (ptr): A = its most letters; bit 7 of A set: the name ends
;;; after a letter with bit 7 clear (Ultima V).  Stops at a zero; bit 7 of
;;; each letter dropped; lower case and $01-$1A (Ultima VI) as capitals.
;;; Padded with spaces to 16 columns.
prname: sta nmode
        and #$7f
        sta nmax
        lda #$00
        sta ncol
        ldy #$00
pn_next:
        cpy nmax
        beq pn_pad
        lda (ptr),y
        beq pn_pad
        sta nch
        jsr pchar
        jsr CHROUT
        inc ncol
        iny
        lda nmode
        bpl pn_next
        lda nch
        bmi pn_next             ; Ultima V: bit 7 clear on the last letter
pn_pad: lda #" "
-       ldx ncol
        cpx #16
        bcs +
        jsr CHROUT
        inc ncol
        bne -
+       rts

;;; a game's letter in A as the launcher's lower-case character set shows
;;; it: bit 7 dropped; $01-$1A (Ultima VI's lower case) and ASCII lower case
;;; to PETSCII $41-$5A, ASCII capitals to $C1-$DA
pchar:  and #$7f
        cmp #$20
        bcs +
        ora #$40                ; $01-$1A: lower case
        rts
+       cmp #$41
        bcc ++
        cmp #$5b
        bcs +
        ora #$80                ; a capital
        rts
+       cmp #$61
        bcc ++
        cmp #$7b
        bcs ++
        and #$df                ; lower case
++      rts

;;; A/X = a 16-bit binary number (lo, hi), in decimal
prdec16:
        sta num
        stx num+1
        lda #$00
        sta bcd
        sta bcd+1
        sta bcd+2
        ldx #16
        sed
-       asl num
        rol num+1
        lda bcd
        adc bcd
        sta bcd
        lda bcd+1
        adc bcd+1
        sta bcd+1
        lda bcd+2
        adc bcd+2
        sta bcd+2
        dex
        bne -
        cld
        jmp prbcd

;;; A = the high BCD byte, X = the low one
prbcd16:
        sta bcd+1
        stx bcd
        lda #$00
        sta bcd+2
;;; bcd (3 bytes, low first), leading zeros dropped, at least one digit;
;;; right-aligned in nwid columns, if the number is shorter (a space for
;;; each zero dropped there).  nwid is the next number's only: 0 after.
prbcd:  lda #$00
        sta lz
        lda #6
        sta npos
        ldx #$02
-       lda bcd,x
        lsr
        lsr
        lsr
        lsr
        jsr digit
        lda bcd,x
        and #$0f
        cpx #$00
        bne +
        inc lz                  ; the last digit always
+       jsr digit
        dex
        bpl -
        lda #$00
        sta nwid
        rts
digit:  dec npos                ; the digits after this one
        cmp #$00
        bne +
        ldy lz
        beq ++
+       ora #"0"
        jsr CHROUT
        inc lz
        rts
++      ldy npos                ; a zero dropped: a space within nwid
        cpy nwid
        bcs +
        lda #" "
        jsr CHROUT
+       rts

