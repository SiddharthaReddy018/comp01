/*
 * vm.c — COMP01 SUBLEQ virtual machine
 * Exact official semantics per PROBLEM.pdf + COMP01_AGENT_BRIEF_v3.md §2B
 *
 * Usage: ./vm program.txt < input.txt
 *   Exit 0: normal halt (pc outside 0..N-3)
 *   Exit 1: error (bad operand, bad file, word out of 32-bit range, bad token)
 *   Exit 2: timeout (step limit reached)
 *
 * Env:
 *   VM_STATS=1          print "halted after N steps" to stderr on normal halt
 *   VM_TRACE=1          print each instruction to stderr before executing
 *   VM_LIMIT=<n>        override step limit (default 100000000)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <ctype.h>

#define N         1048576
#define ADDR_IN   (N - 2)   /* 1048574 */
#define ADDR_OUT  (N - 1)   /* 1048575 */

#define DEFAULT_LIMIT  100000000LL   /* 10^8 */

static int32_t mem[N];

static void die(const char *msg) {
    fprintf(stderr, "%s\n", msg);
    exit(1);
}

/* Load program from file: whitespace-separated decimal integers.
   Each word must fit in int32_t. Image must fit in N words. */
static void load(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "error: cannot open '%s': %s\n", path, strerror(errno));
        exit(1);
    }

    int64_t addr = 0;
    char tok[64];
    int c;

    /* Skip whitespace, read tokens */
    while (1) {
        /* skip whitespace */
        do { c = fgetc(f); } while (c != EOF && isspace((unsigned char)c));
        if (c == EOF) break;

        /* read token */
        int len = 0;
        while (c != EOF && !isspace((unsigned char)c)) {
            if (len < (int)sizeof(tok) - 1) tok[len++] = (char)c;
            else {
                fprintf(stderr, "error: token too long in '%s'\n", path);
                fclose(f);
                exit(1);
            }
            c = fgetc(f);
        }
        tok[len] = '\0';

        /* parse: optional leading minus, then digits */
        char *p = tok;
        int neg = 0;
        if (*p == '-') { neg = 1; p++; }
        if (*p == '\0') {
            fprintf(stderr, "error: bad token '%s' in '%s'\n", tok, path);
            fclose(f);
            exit(1);
        }
        for (char *q = p; *q; q++) {
            if (!isdigit((unsigned char)*q)) {
                fprintf(stderr, "error: bad token '%s' in '%s'\n", tok, path);
                fclose(f);
                exit(1);
            }
        }

        /* convert to int64 to check range */
        int64_t val = 0;
        for (char *q = p; *q; q++) {
            val = val * 10 + (*q - '0');
            if (val > 2147483648LL) {
                fprintf(stderr, "error: word out of 32-bit range: '%s' in '%s'\n", tok, path);
                fclose(f);
                exit(1);
            }
        }
        if (neg) val = -val;

        if (val < -2147483648LL || val > 2147483647LL) {
            fprintf(stderr, "error: word out of 32-bit range: '%s' in '%s'\n", tok, path);
            fclose(f);
            exit(1);
        }

        if (addr >= N) {
            fprintf(stderr, "error: program too large (> %d words) in '%s'\n", N, path);
            fclose(f);
            exit(1);
        }

        mem[addr++] = (int32_t)val;
    }

    fclose(f);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s program.txt < input.txt\n", argv[0]);
        exit(1);
    }

    /* Environment */
    int stats = (getenv("VM_STATS") && strcmp(getenv("VM_STATS"), "1") == 0);
    int trace = (getenv("VM_TRACE") && strcmp(getenv("VM_TRACE"), "1") == 0);

    int64_t limit = DEFAULT_LIMIT;
    const char *lenv = getenv("VM_LIMIT");
    if (lenv) {
        limit = atoll(lenv);
        if (limit <= 0) limit = DEFAULT_LIMIT;
    }

    /* Load program */
    load(argv[1]);

    /* Run */
    int64_t pc = 0;
    int64_t steps = 0;

    /* Input buffer: read stdin lazily byte by byte */
    int input_ended = 0;

    while (pc >= 0 && pc <= (int64_t)(N - 3)) {
        if (steps >= limit) {
            fprintf(stderr, "timeout after %lld steps\n", (long long)steps);
            exit(2);
        }

        int64_t ia = pc, ib = pc + 1, ic = pc + 2;
        int32_t a = mem[ia];
        int32_t b = mem[ib];
        int32_t c = mem[ic];

        if (trace) {
            fprintf(stderr, "pc=%lld: a=%d b=%d c=%d\n",
                    (long long)pc, a, b, c);
        }

        /* Validate a and b */
        if (a < 0 || a >= N) {
            fprintf(stderr, "error: operand a=%d out of range at pc=%lld\n", a, (long long)pc);
            exit(1);
        }
        if (b < 0 || b >= N) {
            fprintf(stderr, "error: operand b=%d out of range at pc=%lld\n", b, (long long)pc);
            exit(1);
        }

        /* IN as a is an error */
        if (a == ADDR_IN) {
            fprintf(stderr, "error: IN used as first operand at pc=%lld\n", (long long)pc);
            exit(1);
        }

        /* Read mem[b] — special case IN */
        int32_t mb;
        if (b == ADDR_IN) {
            if (input_ended) {
                mb = -1;
            } else {
                int ch = fgetc(stdin);
                if (ch == EOF) {
                    input_ended = 1;
                    mb = -1;
                } else {
                    mb = (int32_t)(unsigned char)ch;
                }
            }
        } else {
            mb = mem[b];
        }

        /* Read mem[a] — OUT always reads as 0 */
        int32_t ma;
        if (a == ADDR_OUT) {
            ma = 0;
        } else {
            ma = mem[a];
        }

        /* r = mem[a] - mem[b], 32-bit wraparound via uint32_t */
        int32_t r = (int32_t)((uint32_t)ma - (uint32_t)mb);

        /* Write mem[a] = r — OUT: print, don't store */
        if (a == ADDR_OUT) {
            /* print low 8 bits of r */
            putchar((unsigned char)(r & 0xFF));
            fflush(stdout);
        } else {
            mem[a] = r;
        }

        steps++;

        /* Branch */
        if (r < 0) {
            pc = (int64_t)c;
        } else {
            pc = pc + 3;
        }
    }

    /* Normal halt */
    if (stats) {
        fprintf(stderr, "halted after %lld steps\n", (long long)steps);
    }
    return 0;
}
