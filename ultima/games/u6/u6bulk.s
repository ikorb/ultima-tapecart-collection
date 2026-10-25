;;; u6bulk.s -- Ultima 6's in-game driver, the on-demand part.
;;;
;;; Fetched by the resident part (u6res.s) into the idle half of the sprite
;;; double buffer for every command except a plain sector read, and run from
;;; there: so it is assembled twice, for $D800 and for $DC00 (BULK_ORG), and
;;; it keeps nothing of its own from one call to the next -- whatever must
;;; last (the write session, the log's position) is the resident's.  It
;;; links against the resident through a generated symbol file.
;;;
;;; Handles, re-reading the command from its first byte:
;;;   ^  a read of a sector the game also writes (block map says M_LOGGED):
;;;      the newest logged copy if there is one, else the original
;;;   &  a write: the save area and the BAMs get a log entry each, keyed by
;;;      sector; a chunk file's sectors go into the open write session
;;;   !  a file's first track/sector -- and opens that file's write session
;;;   /NAME, %NAME  a load by name, or a chain of them
;;;
;;; THE WRITE LOG (in U6's save region; compacted at boot by init_u6.s, and
;;; here by u6pack.s -- see b_pack -- when a save finds it full): pages appended at
;;; u6_logdata; every logged unit gets a directory entry written just BELOW
;;; the ones before it, and DIR_SETPARAMS is pointed at it, so the cart's
;;; scan meets the newest version of a key first -- no invalidation, no
;;; erase here.  A logged chunk file is keyed "/NAME", the same key its
;;; original has further on, so a load by name finds whichever is newest.
;;;
;;; $01 is $34 throughout (the resident sets it): this code is under I/O.
;;; Interrupts stay on; the IRQ handler banks I/O in and out around itself.
;;;
;;; With an REU this is assembled as two parts instead (build.py passes
;;; U6_PART_A or U6_PART_B; u6core.s, u6wc.s): A without the writes, B
;;; without the loads by name and with the REU's copies of what is written.

TC_NO_CMDMODE  = 1
TC_NO_FAST     = 1
TC_NO_ERASE    = 1
TC_EXTRAS_ONLY = 1
TC_STREAM_EXACT = 1             ; zx02 takes exactly its stream (tested)
U6_SESSIONS    = 1
!ifndef U6_PART_B {
U6_ZX          = 1
}
!ifdef U6_PART_A {
TC_NO_WRITE    = 1
}
!ifdef U6_PART_B {
TC_NO_STREAM   = 1
}

!source "u6.inc"
!source "u6res_syms.inc"        ; generated: the resident's labels

        * = BULK_ORG

!source "u6core.s"
!ifdef U6_PART_A { !set U6_WC = 1 }
!ifdef U6_PART_B { !set U6_WC = 1 }
!ifdef U6_WC {
!source "u6wc.s"
}

TCLIB_ORG = *
!source "tclib.s"               ; the stream API and tc_write only
!ifndef U6_PART_B {
zx_getbyte = tc_stream_byte
!source "zx02a.s"
}

b_end:
!if >u6_logdir != >u6_sdir {
        !error "u6_logdir and u6_sdir must share a page: b_pp patches only the low byte"
}
!if b_end - BULK_ORG > BULKMAX {
        !error "u6bulk is ", b_end - BULK_ORG - BULKMAX, " bytes over its kilobyte"
}
