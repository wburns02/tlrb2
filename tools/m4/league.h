/* LEAGUE: C port of tools/m4/league.py (contract C16.1): the current league from SYSTEM and the league's dynasty
 * paths. Included by HISTWR, ROSTERS and CREATE (host and DOS). Every function is static; I/O is fopen, fread,
 * fgetc, fclose only; no malloc. league_c/lg_host.c checks it against league.py (test_league.py).
 * lg_current(game_dir, name): name gets 9 bytes, returns 1 when SYSTEM gave the league, 0 for CLASSIC.
 * lg_path(out, cap, which, name, sep): one LG_* path, returns 0 when it does not fit cap (NUL included).
 * game_dir "" or "." is the cwd. The MAJ check uses the native separator; the paths use sep.
 */
#ifndef LG_LEAGUE_H
#define LG_LEAGUE_H

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* each tool uses only some helpers: OpenWatcom -wx -we would fail the build on W202 (unused static) */
#ifdef __WATCOMC__
#pragma disable_message(202)
#define LG_NATIVE '\\'
#else
#define LG_NATIVE '/'
#endif

#define LG_DIR     0
#define LG_HIST    1
#define LG_SNAP    2
#define LG_SEASONS 3
#define LG_RET     4
#define LG_MAJ     5

#define LG_NAME_MAX 8
/* DOS: the game dir is the cwd and the longest path is C:\DYNLG\<L>\SNAP\RETIRED.DAT; keep the stack small */
#ifdef __WATCOMC__
#define LG_PATH_MAX 128
#else
#define LG_PATH_MAX 260
#endif
/* the bytes a league name may not hold (C16.1), with the space and the controls outside 0x21..0x7e */
#define LG_FORBIDDEN "\"*+,./:;<=>?[\\]|"

/* out = the strings in order (NULL ends the list); 0 when they do not fit cap */
static int lg_cats(char *out, int cap, ...)
{
    va_list ap;
    const char *s;
    int l = 0;
    if (cap < 1)
        return 0;
    va_start(ap, cap);
    while ((s = va_arg(ap, const char *)) != NULL) {
        int n = (int)strlen(s);
        if (n > cap - 1 - l) {
            va_end(ap);
            out[0] = 0;
            return 0;
        }
        memcpy(out + l, s, (size_t)n);
        l += n;
    }
    va_end(ap);
    out[l] = 0;
    return 1;
}

/* game_dir + native separator + rest; "" and "." name the cwd */
static int lg_native(char *out, int cap, const char *game_dir, const char *rest)
{
    char sp[2];
    int l = (int)strlen(game_dir);
    sp[0] = LG_NATIVE;
    sp[1] = 0;
    if (l == 0 || (l == 1 && game_dir[0] == '.'))
        return lg_cats(out, cap, rest, NULL);
    if (game_dir[l - 1] == LG_NATIVE)
        return lg_cats(out, cap, game_dir, rest, NULL);
    return lg_cats(out, cap, game_dir, sp, rest, NULL);
}

/* the league name SYSTEM bytes d (got of them read) give, upper-cased into name; 0 when invalid */
static int lg_parse(const unsigned char *d, int got, char name[9])
{
    int i, n = 0;
    while (n < got && n < LG_NAME_MAX && d[n] != 0)
        n++;
    if (n < 1)
        return 0;
    for (i = 0; i < n; i++) {
        unsigned char c = d[i];
        if (c < 0x21 || c > 0x7e || strchr(LG_FORBIDDEN, c) != NULL)
            return 0;
        name[i] = (char)((c >= 'a' && c <= 'z') ? c - 32 : c);
    }
    name[n] = 0;
    return 1;
}

/* 1 when path opens for reading and its first byte reads: a directory fails (open() in Python raises on it) */
static int lg_opens(const char *path)
{
    FILE *f = fopen(path, "rb");
    int c, ok;
    if (!f)
        return 0;
    c = fgetc(f);
    ok = c != EOF || !ferror(f);
    fclose(f);
    return ok;
}

/* the paths of league name (C16.1); the CLASSIC names are the stock DYNSNAP, SEASONS and TEAMS\CLASSIC */
static int lg_path(char *out, int cap, int which, const char *name, char sep)
{
    char sp[2], snap[32];
    int classic = strcmp(name, "CLASSIC") == 0;
    sp[0] = sep;
    sp[1] = 0;
    switch (which) {
    case LG_DIR:
        return lg_cats(out, cap, "TEAMS", sp, name, NULL);
    case LG_HIST:
        return lg_cats(out, cap, "TEAMS", sp, name, sp, "HISTORY.DAT", NULL);
    case LG_SNAP:
        if (classic)
            return lg_cats(out, cap, "C:", sp, "DYNSNAP", NULL);
        return lg_cats(out, cap, "C:", sp, "DYNLG", sp, name, sp, "SNAP", NULL);
    case LG_SEASONS:
        if (classic)
            return lg_cats(out, cap, "C:", sp, "SEASONS", NULL);
        return lg_cats(out, cap, "C:", sp, "DYNLG", sp, name, NULL);
    case LG_RET:
        if (!lg_path(snap, (int)sizeof snap, LG_SNAP, name, sep))
            return 0;
        return lg_cats(out, cap, snap, sp, "RETIRED.DAT", NULL);
    case LG_MAJ:
        return lg_cats(out, cap, "TEAMS", sp, name, sp, name, ".MAJ", NULL);
    }
    return 0;
}

/* the current league (C16.1): name gets SYSTEM's league when valid and its MAJ opens, else CLASSIC */
static int lg_current(const char *game_dir, char name[9])
{
    char path[LG_PATH_MAX], rest[LG_PATH_MAX];
    unsigned char d[LG_NAME_MAX];
    FILE *f;
    int got;
    strcpy(name, "CLASSIC");
    if (!lg_native(path, LG_PATH_MAX, game_dir, "SYSTEM"))
        return 0;
    f = fopen(path, "rb");
    if (!f)
        return 0;
    got = (int)fread(d, 1, sizeof d, f);
    fclose(f);
    if (!lg_parse(d, got, name)
        || !lg_path(rest, LG_PATH_MAX, LG_MAJ, name, LG_NATIVE)
        || !lg_native(path, LG_PATH_MAX, game_dir, rest)
        || !lg_opens(path)) {
        strcpy(name, "CLASSIC");
        return 0;
    }
    return 1;
}

#endif
