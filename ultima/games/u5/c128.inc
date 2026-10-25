;;; c128.inc -- Ultima V in C128 mode: the addresses the pieces share.
;;;
;;; Booted on a C128, Ultima V runs natively, plays music from RAM bank 1 and
;;; caches its command overlays there (and a map in the VDC's RAM): `m` is the
;;; music, `subs.128` the cache, loaded at $7700 over the fastloader -- which
;;; on the cart is our driver.  So in C128 mode subs.128's code runs from bank
;;; 1 instead (sub128.s, at B1_ORG, a range nothing of the game's uses), and
;;; its eight entries at $7700 (seven of the original's and one for the music
;;; setup) are each a JSR C_FAR in the C128 build of the driver.
;;;
;;; What has to be visible in both banks lives in the 1 KiB of common RAM,
;;; in three spots the C128 path leaves alone: $0200-$021F and $0292-$02A1
;;; (the C128 BASIC input buffer, unused by the game) and $0100-$0122, the
;;; bottom of the stack page under the music's own code at $0123 -- which
;;; is the original's bet that the stack never gets that deep, made first.
;;; NOT $0380-$039F, the C64 path's IRQ handler: it is live on a C128 too,
;;; whenever `startup` has copied its RAM vectors over $FFxx and the IRQ
;;; vector says $0380 until the music's next unmute sets $0220 again.

C_FAR    = $0200                ; bank 0 -> bank 1, 31 bytes (the launcher
                                ; loads it: sub128.s far.bin)
C_RTS    = $021e                ; an RTS, C_VEC's default
C_A      = $0292                ; A across the switch
C_IDX    = $0293                ; which entry: the low byte of its JSR's return
C_VEC    = $0294                ; where C_FAR leaves to (2)
C_CFG    = $0296                ; the MMU setting C_B0 loads under
C_B0     = $0100                ; bank 1 -> bank 0, for a load: installed by
                                ; the music setup (19 bytes)
C_PICK   = $0113                ; the driver's reads in bank 1 (c128fast.s,
C_GET    = $011b                ; the launcher loads them): tclib's pick and
C_FAST_END = $0123              ; fetch, 8 bytes each, after C_B0
C_BACK   = $0297                ; and the way back to bank 0 (6 bytes)
C_BACK_END = $02a2
B1_ORG   = $e000                ; sub128.s in bank 1: $E000-$EFFF is free
                                ; there (the cache uses $0400-$6FFF,
                                ; $A000-$DFFF and $F000-$FEFF, the music
                                ; $7200-$9FFF)
MMU_B1   = $7f                  ; bank 1, all RAM: the cache has pages under
                                ; the I/O ($CD-$DF, overlay U), as subs.128's
                                ; FETCH/STASH with $7F did
MMU_B1IO = $7e                  ; bank 1 with I/O, for the VDC
MMU_B0   = $3f                  ; bank 0, all RAM -- the game's $6C06
MMU_IO   = $0e                  ; bank 0, RAM to $BFFF, I/O, KERNAL -- $6C03
SLOTS    = 8                    ; entries at $7700
