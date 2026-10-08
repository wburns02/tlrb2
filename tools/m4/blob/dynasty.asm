; DYNASTY.EXE - M4 season rollover, standalone DOS program (T4a, contract C2/C5).
; Invoked from the patched TONY2.BAT before `control`. Exit code 1 when it
; rolled (including the no-V20 case that only writes the header), else 0.
;   - reads TEAMS\CLASSIC\CLASSIC.MAJ byte 0x20a; acts only when it is 0xf3
;     (season over). No MAJ: exit 0, nothing written.
;   - seed: HISTORY.DAT bytes 1..2 when the file exists and is >= 3 B, else
;     the BIOS tick count low word (int 1Ah AH=00), and 1 when that is 0.
;     start = the rng word in effect at the start of the roll.
;   - rolls every TEAMS\CLASSIC\*.V20 in sorted name order (insertion sort on
;     the 13 B DTA names, matching the Python reference sorted glob), 80
;     records x 143 B, records i / i+40, CX = 3 (progress + retire)
;   - collects per-team retire flags (40 B: the rollover blob's AX for roster
;     record i) into ret_flags, then rewrites C:\DYNSNAP\RETIRED.DAT from
;     scratch (u8 nteam, then per team 13 B NUL padded upper-case name + 40 B
;     flags, in the roll's sorted order; a team that failed to open or read
;     has all-zero flags). Create failure (no C:\DYNSNAP): skipped silently.
;   - day 0xf3, after the teams: HISTORY.DAT keeps its length or grows, never
;     shrinks. Missing -> created as 32 B of zero. Shorter than 32 B ->
;     zero-extended to 32 B (existing bytes kept). Then byte 0 = 1, bytes
;     1..2 = rng after the roll, bytes 8..9 = start. No other byte is touched.
;   - day != 0xf3 with byte 0 = 1: byte 0 = 0 written in place, nothing else
;     touched, length unchanged. Byte 0 = 0 already: nothing written.
;   - core = incbin'd rollover.bin at para offset BLOB_PARA, entry +0x10:
;     DS:SI roster rec, ES:DI season rec, FS:BX rng word, CX flags, AX=retire
; Build: nasm -f bin -o dynasty.img dynasty.asm && python3 build_dynasty.py
BITS 16
CPU 386
org 0

STACK_SIZE   equ 512
TEAM_BYTES   equ 80*143
FILE_BYTES   equ 295 + 80*143    ; team header + 80 records
REC          equ 143
HDR          equ 295             ; team header before record 0
MAX_TEAMS    equ 32
NAME_LEN     equ 13
OFF_YEAR     equ 21              ; record byte: year - 1870
HIST_SIZE    equ 32

entry:
        cld
        mov ax, cs
        mov ds, ax
        mov es, ax
        mov fs, ax

        ; ---- CLASSIC.MAJ day check --------------------------------------
        mov dx, maj_path
        mov ax, 0x3d00                  ; open, read-only
        int 0x21
        jc      x_quiet                 ; no MAJ: not our league, leave quietly
        mov [h], ax
        mov bx, ax
        mov ax, 0x4200                  ; seek from start
        mov cx, 0
        mov dx, 0x20a
        int 0x21
        mov ah, 0x3f
        mov cx, 1
        mov dx, day_byte
        int 0x21
        mov ah, 0x3e
        int 0x21
        cmp byte [day_byte], 0xf3
        jne clear_flag

        ; ---- HISTORY.DAT: done flag + seed --------------------------------
        mov byte [done_flag], 0
        mov word [rng_word], 1          ; fallback when no file / ticks = 0
        mov dx, hist_path
        mov ax, 0x3d00
        int 0x21
        jc seed_ticks                   ; missing file -> ticks
        mov [h], ax                     ; (also saved for the roll-path ops)
        mov bx, ax
        mov ah, 0x3f
        mov cx, 3
        mov dx, hist_buf
        int 0x21
        mov ah, 0x3e
        int 0x21
        cmp ax, 3                       ; bytes 1..2 exist only when >= 3 B
        jb seed_ticks
        mov al, [hist_buf]
        mov [done_flag], al
        mov ax, [hist_buf+1]            ; rng word (LE) at +1
        mov [rng_word], ax
        jmp have_seed
seed_ticks:
        mov ah, 0
        int 0x1a                        ; CX:DX = tick count, AL = 0
        mov [rng_word], dx              ; the low word
        cmp dx, 0
        jne have_seed
        mov word [rng_word], 1          ; xorshift16 seeded 0 stays 0 forever
have_seed:
        mov ax, [rng_word]
        mov [start_seed], ax
        ; copy the rng word into SEG_RNG (the blobs' rng pointer target)
        mov ax, cs
        mov ds, ax
        mov si, rng_word
        mov di, 0                       ; RNG_PHYS is para aligned
        mov cx, 1
        cld
        push es
        mov ax, SEG_RNG
        mov es, ax
        rep movsw
        pop es
        cmp byte [done_flag], 1
        je      x_ok                    ; already rolled at this season stop

        ; ---- enumerate + sort *.V20 -------------------------------------
        mov dx, dta
        mov ah, 0x1a                    ; set DTA
        int 0x21
        mov word [nteam], 0
        mov word [ti], 0                ; retire flag write index (roll order)
        mov dx, find_spec
        mov cx, 0
        mov ah, 0x4e                    ; find first
        int 0x21
        jc do_retired                   ; none found: retiree file + header only
collect:
        mov ax, [nteam]
        cmp ax, MAX_TEAMS
        jae collect_skip
        mov si, dta + 0x1e              ; found name
        mov di, ax
        imul di, di, NAME_LEN
        add di, names
        ; zero-fill the 13 B slot first: DTA leftovers from longer names
        ; must not leak into the stored name
        push di
        mov al, 0
        mov cx, NAME_LEN
zap_name:
        mov [di], al
        inc di
        loop zap_name
        pop di
        mov cx, NAME_LEN
cp_name:
        lodsb
        stosb
        loop cp_name
        inc word [nteam]
collect_skip:
        mov ah, 0x4f                    ; find next
        int 0x21
        jnc collect
        ; insertion sort (uppercase 8.3 names: plain byte compare matches
        ; Python sorted())
        mov word [i], 1
sort_i:
        mov ax, [i]
        cmp ax, [nteam]
        jae sort_done
        mov ax, [i]
        mov [j], ax                     ; j = i
sort_j:
        cmp word [j], 0
        je sort_next
        mov ax, [j]
        dec ax
        imul ax, ax, NAME_LEN
        add ax, names                   ; names[j-1]
        mov si, ax
        mov ax, [j]
        imul ax, ax, NAME_LEN
        add ax, names                   ; names[j]
        mov di, ax
        mov cx, NAME_LEN
cmp_loop:
        lodsb
        cmp al, [di]
        ja do_insert                    ; names[j-1] > names[j] -> swap
        jb sort_next                    ; ordered
        inc di
        loop cmp_loop
        jmp sort_next
do_insert:
        ; swap the names AND the retire-flag slots so ret_flags stays in
        ; ROLL order (ti) while names[] becomes sorted order for the paths
        call swap_j
        call swap_flags
        dec word [j]
        jmp sort_j
sort_next:
        inc word [i]
        jmp sort_i
sort_done:

        ; ---- roll each team ---------------------------------------------
        mov word [ti], 0
team_loop:
        mov ax, [ti]
        cmp ax, [nteam]
        jae do_retired
        imul ax, ax, NAME_LEN
        add ax, names
        mov bx, ax
        ; build path: prefix + name (the stored 13 B slot is NUL padded)
        mov si, prefix
        mov di, work_path
        mov cx, prefix_len
cp_pre:
        lodsb
        stosb
        loop cp_pre
        mov si, bx
        mov cx, NAME_LEN
cp_nm:
        lodsb
        cmp al, 0
        je cp_nm_done
        stosb
        loop cp_nm
cp_nm_done:
        mov al, 0
        stosb
        call roll_team
        inc word [ti]
        jmp team_loop

        ; ---- RETIRED.DAT, then the HISTORY header (this order) -----------
do_retired:
        call write_retired

        ; ---- HISTORY.DAT: grow to >= 32 B, set bytes 0 / 1..2 / 8..9 -----
do_hist_write:
        mov dx, hist_path
        mov ax, 0x3d02                  ; open r/w: keeps the existing bytes
        int 0x21
        jnc hw_open
        ; missing: create, then grow (3Ch only for files that do not exist)
        mov dx, hist_path
        mov cx, 0
        mov ah, 0x3c
        int 0x21
        jc      x_ok
        mov [h], ax                     ; 0 B: grown to 32 B below
        jmp hw_zero
hw_open:
        mov [h], ax
        mov ax, 0x4202                  ; seek to end -> DX:AX = length
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        cmp ax, HIST_SIZE
        jae hw_seek                     ; >= 32 B: keep the length untouched
hw_zero:
        call zero_extend                ; shorter: zero-extend to 32 B
hw_seek:
        ; fill the seed block: bytes 1..2 = rng after the roll, 8..9 = start
        mov ax, [rng_word]
        mov [hist_seed+1], ax
        mov ax, [start_seed]
        mov [hist_start], ax
        mov ax, 0x4200                  ; seek to start
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov bx, [h]
        mov cx, HIST_SIZE
        mov dx, hist_seed
        int 0x21                        ; bytes 0..2 + 8..9 only
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
        ; exit 1: it rolled (including the no-V20 header-only case)
        mov ax, 0x4c01
        jmp exit_dos

; day left 0xf3 without a fresh roll (new season started): clear byte 0 in
; place. One-byte write: nothing else touched, length unchanged.
clear_flag:
        mov dx, hist_path
        mov ax, 0x3d02                  ; r/w
        int 0x21
        jc      x_ok
        mov [h], ax
        mov ah, 0x3f
        mov cx, 1
        mov dx, hist_buf
        int 0x21
        cmp ax, 1
        jb cf_close                     ; empty file: nothing to clear
        cmp byte [hist_buf], 0
        je cf_close                     ; byte 0 already 0: no write at all
        mov byte [hist_buf], 0
        mov ax, 0x4200
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov cx, 1                       ; never CX=0 (DOS truncates on that)
        mov dx, hist_buf
        int 0x21
cf_close:
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
        jmp x_ok

x_quiet:
x_ok:
        mov ax, 0x4c00                  ; exit 0: did not roll
exit_dos:
        int 0x21

; zero-extend the open file (handle [h]) to 32 B, existing bytes kept.
zero_extend:
        mov ax, 0x4200
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x3f
        mov cx, HIST_SIZE
        mov dx, hist_buf
        int 0x21                        ; AX = bytes present, <= 32
        mov di, dx
        add di, ax
        mov cx, HIST_SIZE
        sub cx, ax
        mov al, 0
ze_fill:
        mov [di], al
        inc di
        loop ze_fill
        mov ax, 0x4200
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov cx, HIST_SIZE
        mov dx, hist_buf
        int 0x21
        ret

; swap names[j-1] and names[j] (3-step copy through swap_tmp)
swap_j:
        push cx
        push si
        push di
        mov ax, [j]
        dec ax
        imul ax, ax, NAME_LEN
        add ax, names
        mov si, ax
        mov di, swap_tmp
        mov cx, NAME_LEN
        ; swap_tmp <- names[j-1]
sj1:
        lodsb
        mov [di], al
        inc di
        loop sj1
        mov ax, [j]
        dec ax
        imul ax, ax, NAME_LEN
        add ax, names
        mov di, ax
        mov ax, [j]
        imul ax, ax, NAME_LEN
        add ax, names
        mov si, ax
        mov cx, NAME_LEN
        ; names[j-1] <- names[j]
sj2:
        lodsb
        mov [di], al
        inc di
        loop sj2
        mov ax, [j]
        imul ax, ax, NAME_LEN
        add ax, names
        mov di, ax
        mov si, swap_tmp
        mov cx, NAME_LEN
        ; names[j] <- swap_tmp
sj3:
        lodsb
        mov [di], al
        inc di
        loop sj3
        pop di
        pop si
        pop cx
        ret

; swap ret_flags[(j-1)*40 .. ] and ret_flags[j*40 ..] (same 3-step copy)
swap_flags:
        push cx
        push si
        push di
        mov ax, [j]
        dec ax
        imul ax, ax, 40
        add ax, ret_flags
        mov si, ax
        mov di, flags_tmp
        mov cx, 40
        ; flags_tmp <- ret_flags[(j-1)*40]
sf1:
        lodsb
        mov [di], al
        inc di
        loop sf1
        mov ax, [j]
        dec ax
        imul ax, ax, 40
        add ax, ret_flags
        mov di, ax
        mov ax, [j]
        imul ax, ax, 40
        add ax, ret_flags
        mov si, ax
        mov cx, 40
        ; ret_flags[(j-1)*40] <- ret_flags[j*40]
sf2:
        lodsb
        mov [di], al
        inc di
        loop sf2
        mov ax, [j]
        imul ax, ax, 40
        add ax, ret_flags
        mov di, ax
        mov si, flags_tmp
        mov cx, 40
        ; ret_flags[j*40] <- flags_tmp
sf3:
        lodsb
        mov [di], al
        inc di
        loop sf3
        pop di
        pop si
        pop cx
        ret

; rewrite C:\DYNSNAP\RETIRED.DAT from scratch (create/truncate). nteam, then
; per team 13 B NUL padded name + 40 B flags, all +ti*40 read at once from
; ret_flags. Create fails (no C:\DYNSNAP): skip silently.
write_retired:
        mov dx, ret_path
        mov cx, 0
        mov ah, 0x3c
        int 0x21
        jc      wr_done                 ; no C:\DYNSNAP: silent skip
        mov [h], ax
        mov ax, 0x4200
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov cx, 1
        mov dx, nteam
        int 0x21
        mov ax, [nteam]
        mov cx, ax
        imul cx, cx, 53                 ; 13 B name + 40 B flags per team
        jcxz wr_close
        mov ah, 0x40
        mov dx, names
        int 0x21        ; names[0..nteam-1] and ret_flags[0..] are contiguous:
                        ; write them as one run (13 B name + 40 B flags each)
wr_close:
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
wr_done:
        ret

; roll one team file (ASCIZ path in work_path, roll index [ti]). The team
; image lives in its OWN segment (SEG_TEAM at TEAM_PHYS) so the blobs can
; never write through DS/ES into this program's code or data; the rng word
; lives in SEG_RNG. Both match the unicorn harness layouts (P1/P2).
roll_team:
        mov dx, work_path
        mov ax, 0x3d02                  ; open read+write
        int 0x21
        jnc rt_open
        ret                             ; open failed: all-zero flags (they are)
rt_open:
        mov [h], ax
        mov bx, ax
        mov ah, 0x3f
        mov cx, FILE_BYTES
        mov dx, team_buf
        int 0x21
        cmp ax, FILE_BYTES
        jne rt_close                    ; short read: file untouched, flags zero
        ; copy team_buf -> TEAM_PHYS (the blobs' segment)
        mov ax, cs
        mov ds, ax
        mov si, team_buf
        mov di, 0                       ; TEAM_PHYS is para aligned
        mov cx, (FILE_BYTES + 15) / 16
        mov ax, SEG_TEAM
        mov es, ax
        cld
rt_copy:
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        loop rt_copy
        mov word [pi], 0
pl_loop:
        mov ax, [pi]
        cmp ax, 40
        jae pl_done
        imul ax, ax, REC
        add ax, HDR
        mov si, ax
        add si, TEAM_PHYS & 0xF
        mov di, si
        add di, 40*REC
        mov ax, SEG_TEAM
        mov ds, ax
        mov es, ax
        ; fs:bx -> the rng word in SEG_RNG
        mov ax, SEG_RNG
        mov fs, ax
        mov bx, RNG_PHYS & 0xF
        mov cx, 3                       ; progress + retire
        ; the blob's far address goes in the team segment's tail cell (the
        ; image is 11735 B, the segment is 64k): 'call far' reads it through
        ; DS = SEG_TEAM, the same segment DS:SI already points into
        mov ax, 0x10                    ; the blob's entry offset at [off]
        mov es:[FARPTR_OFF], ax
        mov ax, cs
        add ax, BLOB_PARA               ; the blob's paragraph at [seg]
        mov es:[FARPTR_OFF + 2], ax
        call far [FARPTR_OFF]
pl_ret:
        ; AX = 1 if retired else 0; every other register preserved by the
        ; blob (DF may not be: clear it for the string ops below)
        cld
        ; read the rng word back into cs:rng_word
        push ds
        push es
        mov ax, SEG_RNG
        mov ds, ax
        mov si, RNG_PHYS & 0xF
        mov ax, cs
        mov es, ax
        mov di, rng_word
        movsw
        mov ax, cs
        mov ds, ax
        mov di, [ti]
        imul di, di, 40
        add di, [pi]
        mov [ret_flags + di], al        ; 1 retired this roll, else 0
        pop es
        pop ds
        inc word [pi]
        jmp pl_loop
pl_done:
        ; ---- rookie fill pass (P2) --------------------------------------
        ; Season year byte = any active record's byte 21 (all active players
        ; aged +1 this roll, so the league year is uniform). Skip the fill
        ; entirely if no active record exists.
        mov word [year_byte], 0xFFFF    ; sentinel: none found
        mov word [fi], 0
year_scan:
        mov ax, [fi]
        cmp ax, 80
        jae year_scan_done
        imul ax, ax, REC
        add ax, HDR
        mov si, ax
        add si, TEAM_PHYS & 0xF
        mov ax, SEG_TEAM
        mov ds, ax
        cmp byte [si], 0
        je year_scan_next
        mov al, [si+OFF_YEAR]
        mov [year_byte], al
        jmp year_scan_done
year_scan_next:
        inc word [fi]
        jmp year_scan
year_scan_done:
        mov ax, cs
        mov ds, ax
        cmp word [year_byte], 0xFFFF
        je  no_fill
        mov ax, [year_byte]             ; the fill's season year
        mov [year_input], ax            ; stashed: DS switches below
        ; the fill addresses the team image as DS:SI (base = the image
        ; segment) and writes the rookie records at ES:HDR+slot*REC inside
        ; the same segment
        mov ax, SEG_TEAM
        mov ds, ax
        mov es, ax
        mov si, TEAM_PHYS & 0xF
        mov ax, SEG_RNG
        mov fs, ax
        mov bx, RNG_PHYS & 0xF
        mov ax, [year_input]
        ; the fill's far address in the team segment's tail cell (same as
        ; the roll's call far above)
        mov ax, 0x10
        mov es:[FARPTR_OFF], ax
        mov ax, cs
        add ax, ROOKIE_PARA
        mov es:[FARPTR_OFF + 2], ax
        call far [FARPTR_OFF]
nofill_ret:
        cld                             ; the blob may leave DF set
        mov ax, cs
        mov ds, ax
        mov es, ax
no_fill:
        ; copy TEAM_PHYS -> team_buf, then write the image back
        mov si, TEAM_PHYS & 0xF
        mov ax, SEG_TEAM
        mov ds, ax
        mov di, team_buf
        push es
        mov ax, cs
        mov es, ax
        pop ax
        mov cx, (FILE_BYTES + 15) / 16
tb_copy:
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        movsw
        loop tb_copy
        mov ax, cs
        mov ds, ax
        mov ax, 0x4200                  ; seek to start
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov bx, [h]
        mov cx, FILE_BYTES
        mov dx, team_buf
        int 0x21
rt_close:
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
        ret

; ---------------------------------------------------------------------------
; data
maj_path   db 'TEAMS\CLASSIC\CLASSIC.MAJ', 0
hist_path  db 'TEAMS\CLASSIC\HISTORY.DAT', 0
find_spec  db 'TEAMS\CLASSIC\*.V20', 0
prefix     db 'TEAMS\CLASSIC\'
prefix_len equ $ - prefix
ret_path   db 'C:\DYNSNAP\RETIRED.DAT', 0
day_byte   db 0
hist_buf   db HIST_SIZE dup(0)
; the 32 B seed block written at HISTORY offset 0 after the roll:
; byte 0 = 1, 1..2 = rng after the roll, 8..9 = start, rest zero
hist_seed  db 1
           db 0, 0               ; 1..2 = rng_word
           db 6 dup(0)           ; 3..7 zero
hist_start db 0, 0               ; 8..9 = start_seed
           db 22 dup(0)          ; 10..31 zero
done_flag  db 0
rng_word   dw 1
start_seed dw 0
h          dw 0
nteam      dw 0
ti         dw 0
pi         dw 0
fi         dw 0
year_byte  dw 0
year_input dw 0
i          dw 0
j          dw 0
work_path  db 32 dup(0)
dta        db 43 dup(0)
names      db MAX_TEAMS*13 dup(0)
; ret_flags must be contiguous with names for RETIRED.DAT (13+40 per team);
; the sort temps live after ret_flags
ret_flags  db MAX_TEAMS*40 dup(0)
swap_tmp   db 13 dup(0)
flags_tmp  db 40 dup(0)
team_buf   db FILE_BYTES dup(0)

; team_buf's segment/offset split: the blobs work in their own segments
; (SEG_TEAM holds the team image, SEG_RNG the rng word) so no blob write can
; reach this program's code or data. The rng word in cs:rng_word is synced
; to SEG_RNG:RNG_PHYS before each call and read back after. FARPTR_OFF = the
; far-call cell in the team segment's unused tail (the image is 11735 B).
TEAM_BUF_SEG equ (team_buf - $$) / 16
TEAM_BUF_OFF equ (team_buf - $$) % 16
SEG_TEAM     equ 0x2000
TEAM_PHYS    equ 0x20000
SEG_RNG      equ 0x3000
RNG_PHYS     equ 0x30000
FARPTR_OFF   equ 0xF000

align 16
BLOB_PARA equ ($ - $$) / 16
blob_start:
          incbin 'rollover.bin'
blob_end:

align 16
ROOKIE_PARA equ ($ - $$) / 16
rookie_start:
          incbin 'rookie_fill.bin'
rookie_end:

align 16
db STACK_SIZE dup(0)
image_end:
