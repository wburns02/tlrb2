/* ti_host: parity harness for tools/m4/teamids.h and tools/m4/realign.h (built by build_ti.py).
 *   ti_host teams   MAJ TABLE|- OUT      OUT: 11 B per team (id, L, slot, stem8) in ti_teams order
 *   ti_host maps    MAJ TABLE|- OUT      OUT: 624 B: id_of_engine for e 0..255, id_of_slot for L 0..1 and
 *                                        slot 0..23 (1 B each), slot_of_id for k 0..31 (L, slot or ff ff),
 *                                        stem_of_id for k 0..31 (8 B)
 *   ti_host table   MAJ OUT              OUT: ti_make_table, 256 B
 *   ti_host plan    MAJ HIST|- 0|1 OUTMAJ OUTTAB   stdout: "code N", and "reason R" for code 2
 *   ti_host realign MAJ TARGET OUTMAJ    stdout: "rc N", and "reason R" for rc 1
 * TABLE is a 256 B file or "-" (none). HIST is a file of at most 256 B or "-" (none). exit 0 ok, 2 on any
 * error. Plain stdio, so the same source builds as a 16-bit DOS program (TIHOST.EXE).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "../teamids.h"
#include "../realign.h"

#define MAJ_MAX 65000L
#define HIST_MAX 256L
#define OUT_MAX 624

static uint8_t g_maj[MAJ_MAX];
static uint8_t g_hist[HIST_MAX];
static uint8_t g_tab[TI_TABLE_SIZE];
static uint8_t g_out[OUT_MAX];

/* the whole file, at most max bytes; -1 when it cannot be read or is longer */
static long read_file(const char *path, uint8_t *buf, long max)
{
    FILE *f = fopen(path, "rb");
    long n;
    if (!f)
        return -1;
    n = (long)fread(buf, 1, (size_t)max, f);
    if (ferror(f) || (n == max && fgetc(f) != EOF)) {
        fclose(f);
        return -1;
    }
    fclose(f);
    return n;
}

static int write_file(const char *path, const uint8_t *buf, long n)
{
    FILE *f = fopen(path, "wb");
    int ok;
    if (!f)
        return 0;
    ok = fwrite(buf, 1, (size_t)n, f) == (size_t)n;
    return fclose(f) == 0 && ok;
}

/* the TABLE argument: "-" is no table (*tab stays NULL), else a 256 B file */
static int load_table(const char *arg, const uint8_t **tab)
{
    if (strcmp(arg, "-") == 0) {
        *tab = NULL;
        return 1;
    }
    if (read_file(arg, g_tab, TI_TABLE_SIZE) != TI_TABLE_SIZE)
        return 0;
    *tab = g_tab;
    return 1;
}

static int do_teams(const char *maj, const char *tabarg, const char *out)
{
    TiTeam t[TI_MAX_TEAMS];
    const uint8_t *tab = NULL;
    long len;
    int i, j, n;
    if ((len = read_file(maj, g_maj, MAJ_MAX)) < 0 || !load_table(tabarg, &tab))
        return 2;
    n = ti_teams(g_maj, len, tab, t);
    for (i = 0; i < n; i++) {
        g_out[11 * i] = t[i].id;
        g_out[11 * i + 1] = t[i].L;
        g_out[11 * i + 2] = t[i].slot;
        for (j = 0; j < 8; j++)
            g_out[11 * i + 3 + j] = t[i].stem[j];
    }
    return write_file(out, g_out, 11L * n) ? 0 : 2;
}

static int do_maps(const char *maj, const char *tabarg, const char *out)
{
    const uint8_t *tab = NULL;
    long len;
    int e, L, slot, k, L2, slot2, p = 0;
    if ((len = read_file(maj, g_maj, MAJ_MAX)) < 0 || !load_table(tabarg, &tab))
        return 2;
    for (e = 0; e < 256; e++)
        g_out[p++] = (uint8_t)ti_id_of_engine(g_maj, len, tab, e);
    for (L = 0; L < 2; L++)
        for (slot = 0; slot < TI_SLOTS; slot++)
            g_out[p++] = (uint8_t)ti_id_of_slot(g_maj, len, tab, L, slot);
    for (k = 0; k < 32; k++) {
        if (ti_slot_of_id(g_maj, len, tab, k, &L2, &slot2)) {
            g_out[p++] = (uint8_t)L2;
            g_out[p++] = (uint8_t)slot2;
        } else {
            g_out[p++] = 0xff;
            g_out[p++] = 0xff;
        }
    }
    for (k = 0; k < 32; k++) {
        ti_stem_of_id(g_maj, len, tab, k, g_out + p);
        p += 8;
    }
    return write_file(out, g_out, p) ? 0 : 2;
}

static int do_table(const char *maj, const char *out)
{
    long len;
    if ((len = read_file(maj, g_maj, MAJ_MAX)) < 0)
        return 2;
    ti_make_table(g_maj, len, g_out);
    return write_file(out, g_out, TI_TABLE_SIZE) ? 0 : 2;
}

static int do_plan(const char *maj, const char *histarg, const char *havearg, const char *outmaj,
                   const char *outtab)
{
    const uint8_t *hist = NULL;
    const char *reason = NULL;
    long len, hlen = 0;
    int have = 0, tab_new = 0, code;
    if (strcmp(havearg, "0") == 0)
        have = 0;
    else if (strcmp(havearg, "1") == 0)
        have = 1;
    else
        return 2;
    if (strcmp(histarg, "-") != 0) {
        if ((hlen = read_file(histarg, g_hist, HIST_MAX)) < 0)
            return 2;
        hist = g_hist;
    }
    if ((len = read_file(maj, g_maj, MAJ_MAX)) < 0)
        return 2;
    code = ra_plan(g_maj, len, hist, hlen, have, g_out, &tab_new, &reason);
    printf("code %d\n", code);
    if (code == 2)
        printf("reason %s\n", reason);
    if (!write_file(outmaj, g_maj, len))
        return 2;
    return write_file(outtab, g_out, tab_new ? TI_TABLE_SIZE : 0) ? 0 : 2;
}

static int do_realign(const char *maj, const char *targ, const char *outmaj)
{
    const char *reason = NULL;
    char *end;
    long len, target;
    int rc;
    target = strtol(targ, &end, 10);
    if (end == targ || *end != '\0')
        return 2;
    if ((len = read_file(maj, g_maj, MAJ_MAX)) < 0)
        return 2;
    rc = ra_realign(g_maj, len, (int)target, &reason);
    printf("rc %d\n", rc);
    if (rc == 1)
        printf("reason %s\n", reason);
    return write_file(outmaj, g_maj, len) ? 0 : 2;
}

int main(int argc, char **argv)
{
    if (argc == 5 && strcmp(argv[1], "teams") == 0)
        return do_teams(argv[2], argv[3], argv[4]);
    if (argc == 5 && strcmp(argv[1], "maps") == 0)
        return do_maps(argv[2], argv[3], argv[4]);
    if (argc == 4 && strcmp(argv[1], "table") == 0)
        return do_table(argv[2], argv[3]);
    if (argc == 7 && strcmp(argv[1], "plan") == 0)
        return do_plan(argv[2], argv[3], argv[4], argv[5], argv[6]);
    if (argc == 5 && strcmp(argv[1], "realign") == 0)
        return do_realign(argv[2], argv[3], argv[4]);
    fprintf(stderr, "usage: ti_host teams|maps MAJ TABLE|- OUT | table MAJ OUT | "
                    "plan MAJ HIST|- 0|1 OUTMAJ OUTTAB | realign MAJ TARGET OUTMAJ\n");
    return 2;
}
