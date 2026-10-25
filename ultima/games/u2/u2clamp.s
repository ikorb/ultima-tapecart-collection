;;; u2clamp.s -- counts stop at 99 and 9999: the launcher's V for U2.
;;;
;;; Every number in the player record is BCD ($8E00, the Player disk's
;;; T35/S16), and ULTIMA adds to it with SED / ADC / STA and nothing else:
;;; the carry out of the top digit is dropped, so 99 + 1 is 0 and 9999 + 1
;;; is 0000 -- the Apple II's "overflow", the same on the C64.  Scanned: every byte $F8 in ULTIMA ($5000-$8A8F:
;;; 56, 45 of them SED), every write into $8E15-$8EBF in
;;; ULTIMA, INTRO, SUBS, STARS and DNGNDRAW.  The adds:
;;;   coins $8E22/$8E23 and experience $8E20/$8E21: a kill (KILLED--GOLD+
;;;     ... EXP.+, two ways: $712F/$7159, $7239/$7261), a chest's gold
;;;     ($7925);
;;;   food $8E1D (hundreds; $8E1E units, $8E1F hundredths): the shop's 100
;;;     ($5DB8), Steal food ($8177);
;;;   a weapon $8E40,X, armour $8E60,X, a spell $8E80,X (+5), an item
;;;     $8EA0,X: shops ($64AA, $639A, $5F30, $603A), Steal ($81C4, $819D),
;;;     one picked up from the tile under the party ($7889 WEAPON, $78BB
;;;     ARMOUR), a person paid ($28) and pleased ($7F3A HERE TAKE THIS!), a
;;;     dungeon's chest ($70A4, $70F0);
;;;   keys $8E2F (+2), tools $8E30, torches $8E2E (+1-4), helms $8EA5, the
;;;     tri-lithium $8EAF: a dungeon's chest, the surface's ($795A);
;;;   an attribute $8E15-$8E1A (+4 x the payment $28): a person paid
;;;     ($7F6A ALAKAZAM!).
;;; Hit points cannot wrap: the one add, the king's ($8426), gives +300,
;;; +200, +100 or nothing by how high they are, and nothing from 9900 on.
;;; The rest are subtractions, which the game checks.
;;;
;;; Each add's last STA is hooked at build time (build.py CLAMP_HOOKS, a JSR
;;; in its place; the attribute's run of four ADCs a JMP); with cl_on ($80,
;;; the launch's poke) a carry out stores the top value instead.  The flags
;;; after every hooked STA are dead (CLD, then JMP, JSR or LDX), and the
;;; carry is left as the add made it; without the option every hook stores
;;; what the original did.  In the driver's segment.

cl_on:  !byte 0                 ; the launcher's option: $80 = on (a launch poke)

;;; A = $99 if the add carried out and the option is on
cl_sat: bcc +
        bit cl_on
        bpl +
        lda #$99
+       rts

;;; one byte
cl_wpn: jsr cl_sat              ; a weapon
        sta $8e40,x
        rts
cl_arm: jsr cl_sat              ; armour
        sta $8e60,x
        rts
cl_spl: jsr cl_sat              ; a spell
        sta $8e80,x
        rts
cl_itm: jsr cl_sat              ; an item
        sta $8ea0,x
        rts
cl_trc: jsr cl_sat              ; torches
        sta $8e2e
        rts
cl_key: jsr cl_sat              ; keys
        sta $8e2f
        rts
cl_tol: jsr cl_sat              ; tools
        sta $8e30
        rts
cl_hlm: jsr cl_sat              ; helms
        sta $8ea5
        rts
cl_tri: jsr cl_sat              ; tri-lithium
        sta $8eaf
        rts

;;; two bytes, A the top one: 9999
cl_gld: bcc +                   ; coins
        bit cl_on
        bpl +
        lda #$99
        sta $8e23
+       sta $8e22
        rts
cl_exp: bcc +                   ; experience
        bit cl_on
        bpl +
        lda #$99
        sta $8e21
+       sta $8e20
        rts
cl_fod: bcc +                   ; food, whole rations (the hundredths stay)
        bit cl_on
        bpl +
        lda #$99
        sta $8e1e
+       sta $8e1d
        rts

;;; ALAKAZAM!: $7F6C LDA $8E15,X / ADC $28 x 4 / STA $8E15,X,
;;; carry clear and decimal mode on; a carry out of one ADC is added into
;;; the next, so each is tested.  Back at $7F7A, its CLD.
cl_att: bit cl_on
        bmi +
        lda $8e15,x             ; the original
        adc $28
        adc $28
        adc $28
        adc $28
        sta $8e15,x
        jmp $7f7a
+       lda $8e15,x
        adc $28
        bcs ++
        adc $28
        bcs ++
        adc $28
        bcs ++
        adc $28
        bcc +
++      lda #$99
+       sta $8e15,x
        jmp $7f7a
