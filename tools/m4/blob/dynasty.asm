; DYNASTY.EXE - M4 season rollover, standalone DOS program (P0/P1).
; Invoked from TONY2.BAT at the top of the loop (before `control`). Exits 0
; always so the stock loop proceeds untouched.
;   - reads TEAMS\CLASSIC\CLASSIC.MAJ byte 0x20a; acts only when it is 0xf3
;     (season over)
;   - idempotence + rng state live in TEAMS\CLASSIC\HISTORY.DAT:
;       [0] done flag (1 = rolled this season stop, cleared when day != 0xf3)
;       [1..2] rng word (little endian)
;       [3] reserved
;   - rolls every TEAMS\CLASSIC\*.V20 in sorted name order (matches the Python
;     reference `sorted(glob(...))`), 80 records x 143 B, records i / i+40
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

        ; ---- HISTORY.DAT: done flag + rng state -------------------------
        mov byte [done_flag], 0
        mov word [rng_word], 1          ; default seed matches Rng(1)
        mov dx, hist_path
        mov ax, 0x3d00
        int 0x21
        jc hist_fresh
        mov bx, ax
        mov ah, 0x3f
        mov cx, 4
        mov dx, hist_buf
        int 0x21
        mov ah, 0x3e
        int 0x21
        mov al, [hist_buf]
        mov [done_flag], al
        mov ax, [hist_buf+1]            ; rng word (LE) at +1
        mov [rng_word], ax
hist_fresh:
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
        jc do_hist_write                ; none found: just mark done
collect:
        mov ax, [nteam]
        cmp ax, MAX_TEAMS
        jae collect_skip
        mov si, dta + 0x1e              ; found name
        mov di, ax
        imul di, di, NAME_LEN
        add di, names
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
        mov ax, [ti]
        cmp ax, [nteam]
        jae do_hist_write
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

        ; ---- write HISTORY.DAT marker ------------------------------------
do_hist_write:
        mov dx, hist_path
        mov cx, 0
        mov ah, 0x3c                    ; create/truncate
        int 0x21
        jc      x_ok
        mov bx, ax
        mov byte [hist_buf], 1
        mov ax, [rng_word]
        mov [hist_buf+1], ax
        mov byte [hist_buf+3], 0
        mov ah, 0x40
        mov cx, 4
        mov dx, hist_buf
        int 0x21
        mov ah, 0x3e
        int 0x21
x_ok:
        mov ax, 0x4c00
        int 0x21

; day left 0xf3 without a fresh roll (new season started): clear the flag
clear_flag:
        mov dx, hist_path
        mov ax, 0x3d00
        int 0x21
        jc      x_ok
        mov bx, ax
        mov ah, 0x3f
        mov cx, 4
        mov dx, hist_buf
        int 0x21
        mov ah, 0x3e
        int 0x21
        cmp byte [hist_buf], 0
        je      x_ok
        mov byte [hist_buf], 0
        mov dx, hist_path
        mov cx, 0
        mov ah, 0x3c
        int 0x21
        jc      x_ok
        mov bx, ax
        mov ah, 0x40
        mov cx, 4
        mov dx, hist_buf
        int 0x21
        mov ah, 0x3e
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
        mov si, ax
        mov di, swap_tmp
        mov cx, NAME_LEN
sj1:
        lodsb
        xchg al, [di]
        mov [si-1], al
        inc di
        loop sj1
        mov ax, [j]
        imul ax, ax, NAME_LEN
        add ax, names
        mov si, swap_tmp
        mov di, ax
        mov cx, NAME_LEN
sj2:
        lodsb
        stosb
        loop sj2
        pop di
        pop si
        pop cx
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
        cmp word [year_byte], 0xFFFF
        je  no_fill
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
day_byte   db 0
hist_buf   db 4 dup(0)
done_flag  db 0
rng_word   dw 1
h          dw 0
nteam      dw 0
ti         dw 0
pi         dw 0
fi         dw 0
year_byte  dw 0
farptr2    dw 0, 0
i          dw 0
j          dw 0
farptr     dw 0, 0
work_path  db 32 dup(0)
dta        db 43 dup(0)
names      db MAX_TEAMS*NAME_LEN dup(0)
swap_tmp   db NAME_LEN dup(0)
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
