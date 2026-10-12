/* LG_HOST: host harness for tools/m4/league.h (test_league.py checks it against league.py, C16.1).
 * usage: lg_host GAME_DIR SEP   (SEP is / or \)
 * prints name=<L>, fromsys=<0|1>, then one line each for dir, hist, snap, seasons, ret, maj.
 * exit 0 ok, 2 on bad usage or a path that does not fit.
 */
#include <stdio.h>

#include "../league.h"

int main(int argc, char **argv)
{
    static const char *const keys[6] = { "dir", "hist", "snap", "seasons", "ret", "maj" };
    char name[9], buf[LG_PATH_MAX];
    int fromsys, k;
    if (argc != 3 || (argv[2][0] != '/' && argv[2][0] != '\\') || argv[2][1] != 0) {
        fprintf(stderr, "usage: lg_host GAME_DIR SEP\n");
        return 2;
    }
    fromsys = lg_current(argv[1], name);
    printf("name=%s\n", name);
    printf("fromsys=%d\n", fromsys);
    for (k = 0; k < 6; k++) {
        if (!lg_path(buf, LG_PATH_MAX, k, name, argv[2][0]))
            return 2;
        printf("%s=%s\n", keys[k], buf);
    }
    return 0;
}
