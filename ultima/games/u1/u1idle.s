;;; u1idle.s -- the outdoor turn that passes on an idle keyboard, by the clock.
;;;
;;; OU's key wait ($8DD0) polls ST's $167C and lets a turn pass after 128
;;; polls without a key.  Each poll draws the view and flips on the frame:
;;; six frames in the original (15.3 s on a PAL machine), two to four with
;;; the view drawn only where it changed (u1view.s).  So the wait is timed
;;; here instead: the turn passes 15 s into it, by CIA 2's time of day, which
;;; the game leaves alone (init_u1.s gives it its 50 Hz input on a PAL
;;; machine).  The page's P (PT_PASS: no turn passes) is read here; OU's own
;;; loop is not patched for it.
;;;
;;; OU $8DD0 is a JMP here (build.py IDLE_HOOK).  Returns as OU's: A and X
;;; the key (Z clear), or 0 when the turn passes (Z set).

IDLE_SECS = $15                 ; BCD: 15 s

idle:   lda #$00
        sta $dd09               ; CIA 2's time of day to 0.0 s (its tenths
        sta $dd08               ; written last: it runs)
-       jsr $167c               ; ST: the view drawn, a key?
        bne +
        lda pt_opts
        and #PT_PASS
        bne -                   ; P: no turn passes
        lda $dd09
        cmp #IDLE_SECS
        bcc -
        lda #$00
+       tax
        rts
