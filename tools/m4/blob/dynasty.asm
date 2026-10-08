; DYNASTY.EXE - M4 season rollover, standalone DOS program (contract C2/C5).
; Invoked from the patched TONY2.BAT before `control`. Exit code 1 when it
; rolled (including the no-V20 case that only writes the header), else 0.
;   - reads TEAMS\CLASSIC\CLASSIC.MAJ byte 0x20a; acts only when it is 0xf3
;     (season over). No MAJ: exit 0, nothing written.
;   - TEAMS\CLASSIC\HISTORY.DAT header (DYNASTY owns bytes 0..2 and 8..9):
;       [0] done flag (1 = rolled this season stop, cleared when day != 0xf3)
;       [1..2] rng word, [8..9] start seed of the last roll (little endian)
;     seed = bytes 1..2 when the file is >= 3 B and they are nonzero, else the
;     BIOS tick count low word (int 1Ah), and 1 when that is 0.
;     The file is only ever patched in place: it keeps its length or grows
;     (missing -> 32 B of zero, shorter -> zero-extended to 32 B).
;   - rolls every TEAMS\CLASSIC\*.V20 in sorted name order (matches the Python
;     reference `sorted(glob(...))`), 80 records x 143 B, records i / i+40
;   - C:\DYNSNAP\RETIRED.DAT rewritten after each roll: u8 nteam, then per
;     team 13 B NUL padded name + 40 B flags (blob AX per roster record).
;     No C:\DYNSNAP: skipped silently.
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
        jc      x_ok                    ; no MAJ: not our league, leave quietly
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
        mov word [hist_len], 0
        mov dx, hist_path
        mov ax, 0x3d00
        int 0x21
        jc seed_ticks                   ; missing file
        mov bx, ax
        mov ah, 0x3f
        mov cx, 3
        mov dx, hist_buf
        int 0x21
        jc hr_close
        mov [hist_len], ax              ; bytes present, 0..3
hr_close:
        mov ah, 0x3e
        int 0x21
        cmp word [hist_len], 1
        jb seed_ticks
        mov al, [hist_buf]
        mov [done_flag], al
        cmp word [hist_len], 3
        jb seed_ticks                   ; no rng word in a 1..2 B file
        mov ax, [hist_buf+1]            ; rng word (LE) at +1
        or ax, ax
        jnz have_seed
seed_ticks:
        mov ah, 0
        int 0x1a                        ; CX:DX = ticks
        mov ax, dx
        or ax, ax
        jnz have_seed
        mov ax, 1                       ; xorshift seeded 0 stays 0
have_seed:
        mov [rng_word], ax
        mov [start_seed], ax
        cmp byte [done_flag], 1
        je      x_ok                    ; already rolled at this season stop

        ; ---- enumerate + sort *.V20 -------------------------------------
        mov dx, dta
        mov ah, 0x1a                    ; set DTA
        int 0x21
        mov word [nteam], 0
        mov dx, find_spec
        mov cx, 0
        mov ah, 0x4e                    ; find first
        int 0x21
        jc do_retired                   ; none found: RETIRED + header only
collect:
        mov ax, [nteam]
        cmp ax, MAX_TEAMS
        jae collect_skip
        mov si, dta + 0x1e              ; found name
        mov di, ax
        imul di, di, NAME_LEN
        add di, names
        mov cx, NAME_LEN
        mov dl, 0                       ; 1 once the NUL is seen
cp_name:
        lodsb
        or dl, dl
        jz cpn_keep
        mov al, 0                       ; DTA leftovers after the NUL: zero
cpn_keep:
        or al, al
        jnz cpn_store
        mov dl, 1
cpn_store:
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
        call swap_j
        dec word [j]
        jmp sort_j
sort_next:
        inc word [i]
        jmp sort_i
sort_done:

        ; ---- roll each team ---------------------------------------------
        mov word [ti], 0
team_loop:
        cld                             ; the blobs need not preserve DF
        mov ax, [ti]
        cmp ax, [nteam]
        jae do_retired
        imul ax, ax, NAME_LEN
        add ax, names
        mov bx, ax
        ; build path: prefix + name
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

        ; ---- RETIRED.DAT, then the HISTORY header, then exit -------------
do_retired:
        call write_retired

        ; HISTORY.DAT is patched in place: never 3Ch on an existing file and
        ; never 40h with CX=0 (both truncate)
        mov dx, hist_path
        mov ax, 0x3d02                  ; open r/w
        int 0x21
        jnc hw_open
        mov dx, hist_path
        mov cx, 0
        mov ah, 0x3c                    ; missing: create (0 B)
        int 0x21
        jc      x_rolled
hw_open:
        mov [h], ax
        mov bx, ax
        mov ax, 0x4202                  ; seek to end: DX:AX = length
        mov cx, 0
        mov dx, 0
        int 0x21
        or dx, dx
        jnz hw_patch
        cmp ax, HIST_SIZE
        jae hw_patch
        mov cx, HIST_SIZE               ; short: append zeros up to 32 B
        sub cx, ax                      ; 1..32, never 0
        mov dx, zeros
        mov ah, 0x40
        int 0x21
hw_patch:
        mov byte [hist_buf], 1
        mov ax, [rng_word]
        mov [hist_buf+1], ax
        mov ax, 0x4200                  ; bytes 0..2 = 1, rng after the roll
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov cx, 3
        mov dx, hist_buf
        int 0x21
        mov ax, 0x4200                  ; bytes 8..9 = start seed
        mov cx, 0
        mov dx, 8
        int 0x21
        mov ah, 0x40
        mov cx, 2
        mov dx, start_seed
        int 0x21
        mov ah, 0x3e
        int 0x21
x_rolled:
        mov ax, 0x4c01
        int 0x21
x_ok:
        mov ax, 0x4c00
        int 0x21

; day left 0xf3 without a fresh roll (new season started): clear byte 0 in
; place, nothing else touched
clear_flag:
        mov dx, hist_path
        mov ax, 0x3d02
        int 0x21
        jc      x_ok
        mov [h], ax
        mov bx, ax
        mov ah, 0x3f
        mov cx, 1
        mov dx, hist_buf
        int 0x21
        jc cf_close
        cmp ax, 1
        jb cf_close                     ; empty file
        cmp byte [hist_buf], 0
        je cf_close
        mov byte [hist_buf], 0
        mov ax, 0x4200
        mov bx, [h]
        mov cx, 0
        mov dx, 0
        int 0x21
        mov ah, 0x40
        mov cx, 1
        mov dx, hist_buf
        int 0x21
cf_close:
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
        jmp x_ok

; swap names[j-1] and names[j]
swap_j:
        push cx
        push si
        push di
        mov ax, [j]
        dec ax
        imul ax, ax, NAME_LEN
        add ax, names
        mov si, ax                      ; names[j-1]
        lea di, [si+NAME_LEN]           ; names[j]
        mov cx, NAME_LEN
sj:
        mov al, [si]
        mov ah, [di]
        mov [si], ah
        mov [di], al
        inc si
        inc di
        loop sj
        pop di
        pop si
        pop cx
        ret

; C:\DYNSNAP\RETIRED.DAT from scratch: u8 nteam, then per team (sorted roll
; order) 13 B name + 40 B flags
write_retired:
        mov dx, ret_path
        mov cx, 0
        mov ah, 0x3c
        int 0x21
        jc      wr_done                 ; no C:\DYNSNAP: silent skip
        mov [h], ax
        mov bx, ax
        mov ah, 0x40
        mov cx, 1
        mov dx, nteam                   ; low byte (nteam <= 32)
        int 0x21
        mov word [wi], 0
wr_loop:
        mov ax, [wi]
        cmp ax, [nteam]
        jae wr_close
        imul dx, ax, NAME_LEN
        add dx, names
        mov ah, 0x40
        mov bx, [h]
        mov cx, NAME_LEN
        int 0x21
        mov ax, [wi]
        imul dx, ax, 40
        add dx, ret_flags
        mov ah, 0x40
        mov bx, [h]
        mov cx, 40
        int 0x21
        inc word [wi]
        jmp wr_loop
wr_close:
        mov ah, 0x3e
        mov bx, [h]
        int 0x21
wr_done:
        ret

; roll one team file (ASCIZ path in work_path)
roll_team:
        mov dx, work_path
        mov ax, 0x3d02                  ; open read+write
        int 0x21
        jnc rt_open
        ret
rt_open:
        mov [h], ax
        mov bx, ax
        mov ah, 0x3f
        mov cx, FILE_BYTES
        mov dx, team_buf
        int 0x21
        cmp ax, FILE_BYTES
        jne rt_close
        mov ax, cs
        add ax, BLOB_PARA
        mov [farptr+2], ax
        mov word [farptr], 0x10
        mov word [pi], 0
pl_loop:
        mov ax, [pi]
        cmp ax, 40
        jae pl_done
        imul ax, ax, REC
        add ax, HDR
        mov si, ax
        add si, team_buf
        mov di, si
        add di, 40*REC
        mov ax, cs
        mov ds, ax
        mov es, ax
        mov fs, ax
        mov bx, rng_word
        mov cx, 3                       ; progress + retire
        call far [farptr]
        mov di, [ti]                    ; DS = CS still (blob preserves it)
        imul di, di, 40
        add di, [pi]
        mov [ret_flags + di], al        ; 1 retired this roll, else 0
        inc word [pi]
        jmp pl_loop
pl_done:
        ; ---- rookie fill pass (P2) --------------------------------------
        ; Season year byte = any active record's byte 21 (all active players
        ; aged +1 this roll, so the league year is uniform). A file with no
        ; active record (a blank pool) takes the last year found in an earlier
        ; file (C4 amendment 2026-10-07); skip the fill only if none was.
        mov word [year_byte], 0xFFFF    ; sentinel: none found
        mov word [fi], 0
year_scan:
        mov ax, [fi]
        cmp ax, 80
        jae year_scan_done
        imul ax, ax, REC
        add ax, HDR
        mov si, ax
        add si, team_buf
        cmp byte [si], 0
        je year_scan_next
        mov al, [si+OFF_YEAR]
        mov [year_byte], al
        jmp year_scan_done
year_scan_next:
        inc word [fi]
        jmp year_scan
year_scan_done:
        mov ax, [year_byte]
        cmp ax, 0xFFFF
        jne year_found
        mov ax, [last_year]
        mov [year_byte], ax
        cmp ax, 0xFFFF
        je  no_fill
year_found:
        mov [last_year], ax
        mov ax, cs
        add ax, ROOKIE_PARA
        mov [farptr2+2], ax
        mov word [farptr2], 0x10
        mov ax, cs
        mov ds, ax
        mov es, ax
        mov fs, ax
        mov si, team_buf
        mov bx, rng_word
        mov ax, [year_byte]
        call far [farptr2]
no_fill:
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
hist_buf   db 4 dup(0)
hist_len   dw 0
zeros      db HIST_SIZE dup(0)
done_flag  db 0
rng_word   dw 1
start_seed dw 0
wi         dw 0
h          dw 0
nteam      dw 0
ti         dw 0
pi         dw 0
fi         dw 0
year_byte  dw 0
last_year  dw 0xFFFF                    ; once per run: files are rolled in one pass
farptr2    dw 0, 0
i          dw 0
j          dw 0
farptr     dw 0, 0
work_path  db 32 dup(0)
dta        db 43 dup(0)
names      db MAX_TEAMS*NAME_LEN dup(0)
ret_flags  db MAX_TEAMS*40 dup(0)
team_buf   db FILE_BYTES dup(0)

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
