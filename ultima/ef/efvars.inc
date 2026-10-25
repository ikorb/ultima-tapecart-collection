;;; efvars.inc -- what the EasyFlash build's pieces agree on (ultima/ef/build.py
;;; passes the layout's numbers in as -D defines; these are fixed).
;;;
;;; FLASH ADDRESSES are linear, 24 bits, in EAPI's "lhlh" order: bank n's
;;; ROML is n * $4000, its ROMH n * $4000 + $2000.  So with the cart in 16K
;;; mode a linear address shows at $8000 | (addr & $3FFF) in bank addr >> 14,
;;; and a 64 KiB erase sector (8 banks of one chip) is half of a 128 KiB run.

EF_BANK_REG = $de00
EF_CTRL_REG = $de02
EF_16K      = $07               ; ROML at $8000, ROMH at $A000 (with HIRAM)
EF_16K_LED  = $87               ; ... and the LED, while the cart is busy
EF_OFF      = $04               ; cartridge ROM off ($DF00 RAM stays)

;;; EAPI (EasyFlash ProgRef, chapter EasyAPI): its jump table, which
;;; EAPIInit sets up in the cart's RAM at $DF80-$DFFF.  Its code stays in
;;; the C64 RAM it was copied to, page aligned; EAPIInit is at that page + 20.
EAPI_WRITE      = $df80
EAPI_ERASE      = $df83
EAPI_SETBANK    = $df86
EAPI_GETBANK    = $df89
EAPI_SETPTR     = $df8c
EAPI_SETLEN     = $df8f
EAPI_READINC    = $df92
EAPI_WRITEINC   = $df95
EAPI_INIT_OFF   = 20
EAPI_SIZE       = $0300         ; reserved for any version (ProgRef)
EAPI_LHLH       = $d0           ; EAPISetPtr's bank mode for linear addresses

;;; THE STATE that outlives one call and one program: in the cart's RAM at
;;; $DF00-$DF7F, which ProgRef leaves to the application (EAPI has
;;; $DF80-$DFFF).  Visible whenever I/O is ($01 = $35/$37), whatever the
;;; banking, and nothing of Ultima VI ever touches it -- so the boot's log
;;; scan hands its result to the boot driver and to `game`'s with no copy.
EF_LOGDIR   = $df00             ; the log's newest directory entry (3)
EF_DIRCOUNT = $df03             ; its entries (2)
EF_LOGDATA  = $df05             ; the next free page (3)
EF_OPEN     = $df08             ; a chunk file's write session is open
EF_SCOUNT   = $df09             ;   pages written in it
EF_SSTART   = $df0a             ;   where they start (3)
EF_SKEY     = $df0d             ;   its key, "/NAME" (12)
EF_FRESH    = $df19             ; the world has been reset this boot
EF_ACT      = $df1a             ; the active half: 0 or 3 (as init's tables)
EF_GEN      = $df1b             ; its generation (2)
EF_ERR      = $df1d             ; the last EAPI error (0: none)
;;; a chunk file's session, page by page (efdrv.s dw_chunk): pages that
;;; equal the file's newest version are held back while every one so far
;;; has, so a file saved unchanged costs no write at all
EF_SPAGE    = $df1e             ;   pages the game has written so far
EF_SLAST    = $df1f             ;   the last held back was the file's last
EF_OADDR    = $df20             ;   the newest version: address (3),
EF_OLEN     = $df23             ;   length (2: pages, or bytes if raw),
EF_OFLAG    = $df25             ;   flags ($FF: there is none)
;;; the in-game compaction (efdrv.s d_pack)
P_WALK      = $df26             ; the old directory, walked (3)
P_LEFT      = $df29             ;   entries left in it (2)
P_NDATA     = $df2b             ; the new half: its next page (3)
P_SRC       = $df2e             ; a copy's source (3)
P_NDIR      = $df31             ; the new directory's newest entry (3)
P_NLIVE     = $df34             ;   entries in it (2)
P_NPAGES    = $df36             ; a copy's pages (2)
P_TGT       = $df38             ; the new half: 0 or 3
P_FRAME     = $df39             ; the spinner's frame
P_WSRC      = $df3a             ; the command's own page, kept (2)
P_BUF       = $df3c             ; the idle sprite half: $D8 or $DC
P_SC        = $df3d             ; the spinner cell's colours, kept
P_SEEN      = $df3e             ; keys copied: a bit for each the game logs (18)
EF_STATE_END = $df50

KEYLEN   = 12
DATALEN  = 8
ENTRYLEN = KEYLEN + DATALEN
F_ZX     = %00000001
F_LINKS  = %00000010
M_LOGGED = $ff
M_BAM    = $fe
K_SECTOR = $01
K_HEADER = $fe
MAXHOLD  = 10                   ; pages a session holds back at most (the
                                ; largest chunk file has 9)
