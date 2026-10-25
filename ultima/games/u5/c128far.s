;;; c128far.s -- the C128 build's way into bank 1, in common RAM at $0200.
;;;
;;; Each of subs.128's entries at $7700 (the C128 build of u5drv.s) is a
;;; `jsr C_FAR`; the return address it pushes says which.  This drops it,
;;; keeps the caller's MMU setting on the stack for sub128.s to read, calls
;;; sub128.s in bank 1 with A, X and Y as the caller left them, and leaves
;;; in the configuration sub128.s hands back in A, with A = C_A and X, Y and
;;; the carry as sub128.s left them -- through C_VEC, which is an RTS unless
;;; the entry ends in a jump into the game (the mode swap's JMP $8000).
;;;
;;; The switch has to be in RAM both banks see, and this is all of it that
;;; must be: 31 bytes of the 32 there are.

!source "c128.inc"

        * = C_FAR
        sta C_A
        pla                     ; the entry's return address: its low byte
        sta C_IDX               ; tells the entries apart
        pla
        lda $ff00               ; the caller's configuration, for sub128.s
        pha
        lda #MMU_B1
        sta $ff00
        jsr B1_ORG
        sta $ff00
        pla
        lda C_A
        jmp (C_VEC)
!if * != C_RTS {
        !error "C_RTS moved: ", *
}
        rts
!if * > C_FAR + $20 {
        !error "c128far.s runs into $0220, the music's IRQ handler"
}
