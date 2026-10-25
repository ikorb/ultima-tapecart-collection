;;; init_u0.s -- Akalabeth's machine setup, run by the menu after loading.
;;;
;;; Akalabeth is a compiled BASIC program: a runtime at $081C (the target of
;;; its line `SYS 2076`) that interprets its own p-code, and calls BASIC's ROM
;;; for its arithmetic, strings and errors.  A player would LOAD and RUN it;
;;; the menu has put it in RAM instead, with LIB, the graphics routines the
;;; program would load to $C000 itself (ultima/games/u0/build.py).  What RUN
;;; would find, set up here: BASIC's vectors and zero page as after power-on
;;; (CHRGET, the string stack at $16 -- a stale one is ?FORMULA TOO COMPLEX
;;; -- and the memory pointers, from MEMBOT and MEMTOP).  The runtime sets
;;; the variables' pointers itself, from its own table.
;;;
;;; The segment runs to $03FF: its last four bytes are the trainer's flags,
;;; which the game reads as PEEK(1020)-PEEK(1023) = 100 (the page's options,
;;; poked in after the segments load and before this runs).  The tape
;;; buffer is free after this: the program never uses the tape.

ORG = $0334
FLAGS = $03FC

        * = ORG

        sei
        lda #$2f
        sta $00
        lda #$37                ; BASIC, KERNAL and I/O; motor bit set
        sta $01
        lda #$00                ; MEMBOT $0800, MEMTOP $A000, as RAMTAS
        sta $0281               ; leaves them
        sta $0283
        lda #$08
        sta $0282
        lda #$a0
        sta $0284
        jsr $e453               ; BASIC's vectors
        jsr $e3bf               ; BASIC's zero page and memory pointers
        lda #$00                ; drop the keypress that chose this game
        sta $c6
        ;; The KERNAL's IRQ starts the tape motor while $C0 is zero and the
        ;; cart holds sense low; Akalabeth never touches the cart, but a
        ;; motor pulse would drop it from command mode for nothing.
        lda #$01
        sta $c0
        cli
        jmp $081c               ; SYS 2076

code_end:
!if code_end > FLAGS {
        !error "the init stub runs into the trainer's flags by ", code_end - FLAGS
}
        !fill FLAGS - code_end, 0
        ;; PEEK(1020) always hit, always kill; 1021 invincible; 1022
        ;; unlimited gold; 1023 unlimited food: 100 is on
        !byte 0, 0, 0, 0
