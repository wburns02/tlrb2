/* sl_host: parity harness for tools/m4/statline.h (built by build_sl.py).
 *   sl_host fill IN OUT     IN: N x 143 B records; OUT: each record after sl_fill
 *   sl_host repair IN OUT   IN: N x 11735 B V20 images; OUT: each after sl_repair_image
 *   sl_host salary IN OUT   IN: N x 143 B records; OUT: N x 2, u16 LE sl_salary of each
 * exit 0 ok, 2 on any error. Plain stdio, so the same source builds as a 16-bit DOS
 * program (SLHOST.EXE).
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

#define STATLINE_REPAIR
#include "../statline.h"

#define IMAGE_LEN 11735

static uint8_t g_buf[IMAGE_LEN];

static int run_salary(FILE *in, FILE *out)
{
    size_t n;
    while ((n = fread(g_buf, 1, SL_RECORD_LEN, in)) == (size_t)SL_RECORD_LEN) {
        uint8_t b[2];
        long sal = sl_salary(g_buf);
        b[0] = (uint8_t)(sal & 0xff);
        b[1] = (uint8_t)((sal >> 8) & 0xff);
        if (fwrite(b, 1, 2, out) != 2)
            return 2;
    }
    return (n != 0 || ferror(in)) ? 2 : 0;
}

static int run_fill(FILE *in, FILE *out)
{
    size_t n;
    while ((n = fread(g_buf, 1, SL_RECORD_LEN, in)) == (size_t)SL_RECORD_LEN) {
        sl_fill(g_buf);
        if (fwrite(g_buf, 1, SL_RECORD_LEN, out) != (size_t)SL_RECORD_LEN)
            return 2;
    }
    return (n != 0 || ferror(in)) ? 2 : 0;
}

static int run_repair(FILE *in, FILE *out)
{
    size_t n;
    while ((n = fread(g_buf, 1, IMAGE_LEN, in)) == (size_t)IMAGE_LEN) {
        (void)sl_repair_image(g_buf);
        if (fwrite(g_buf, 1, IMAGE_LEN, out) != (size_t)IMAGE_LEN)
            return 2;
    }
    return (n != 0 || ferror(in)) ? 2 : 0;
}

int main(int argc, char **argv)
{
    FILE *in, *out;
    int rc;
    if (argc != 4) {
        fprintf(stderr, "usage: sl_host fill|repair|salary IN OUT\n");
        return 2;
    }
    in = fopen(argv[2], "rb");
    if (!in)
        return 2;
    out = fopen(argv[3], "wb");
    if (!out) {
        fclose(in);
        return 2;
    }
    if (strcmp(argv[1], "fill") == 0)
        rc = run_fill(in, out);
    else if (strcmp(argv[1], "repair") == 0)
        rc = run_repair(in, out);
    else if (strcmp(argv[1], "salary") == 0)
        rc = run_salary(in, out);
    else
        rc = 2;
    fclose(in);
    if (fclose(out) != 0)
        rc = 2;
    return rc;
}
