;;; u6key.s -- `game`'s keyboard queue, in its IRQ's input handler: the
;;; original's $1F76-$1FB6, rewritten in the same 65 bytes (build.py
;;; KEY_QUEUE asserts the original and splices this in).
;;;
;;; The original queued a key when it differed from the last one seen ($43),
;;; or, for the same key, when the repeat count $0197 ran out -- and on a
;;; release it did nothing, so $43 kept the key and $0197 stopped counting.
;;; A second tap of the same key then counted as the first still held: it
;;; was only queued if held past the count, ~9 frames from the last press,
;;; whatever the gap between the taps.  Return or space twice through a
;;; conversation, Y after Y: every second quick tap went missing (measured
;;; in VICE, frame by frame: 4 frames, 3 or 12 up, 4 frames -- one key).
;;;
;;; Now a frame with no key counts down $0197 as a held one does, stopping
;;; at zero: a tap of the same key is queued if it is down when a held key
;;; would have repeated (the 10th frame after the last one queued) -- 4
;;; down, 3 up, 4 down is two keys -- and a key that bounces up for a frame
;;; mid-press is exactly as if it had been held.  Held keys repeat as before.
;;; The room: the direction-key search ($2063/$206D, ten keys merged into
;;; the joystick bits $47) uses the key still in A from $1F71, counts down
;;; with one branch fewer, and knows the one with the fire bit by its index,
;;; 9 (Return; build.py checks the table).

        * = $1f76
k_exit  = $1fb7
        ldx #$0a
-       dex
        bmi k_queue             ; not a direction key
        cmp $2063,x             ; A: the key ($1F71 stored it in $0196)
        bne -
        lda $206d,x             ; a direction: into the joystick bits
        ora $47
        sta $47
        cpx #$09
        bne k_exit              ; and only there, but Return (fire) is a key
k_queue:
        dec $01                 ; ($34: the queue is under I/O)
        ldx $45
        cpx #$1b
        bcs k_out               ; full
        lda $0196
        beq k_up                ; no key
        cmp $43
        sta $43
        bne k_new               ; another key than last time
        dec $0197               ; the same, held -- or back after a gap
        bpl k_out               ; shorter than the repeat's
k_new:  sta $d7e4,x
        inc $45
        lda #$09                ; (k_up makes it 8, the original's)
        sta $0197
k_up:   dec $0197               ; no key: the time counts as if held,
        bpl k_out               ; down to zero
        inc $0197
k_out:  inc $01
!if * != k_exit {
        !error "u6key.s must end at $1FB7, not ", *
}
