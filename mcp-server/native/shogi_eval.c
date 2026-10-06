/*
 * 浅い探索用の評価関数(材料点 + 玉の危険度)のネイティブ実装(02_design.md §34, §37)。
 * analysis.py の _eval_python と同じ値を返す。
 *
 * 利きの定義は shogi_core.c の駒の動きの表を使う(Python側の利き表は不要)。
 * 駒の価値・持ち駒の価値・玉の危険度の重み(5種、§40.3)だけをPythonが shogi_init() で渡す
 * (価値の定義をC側に二重に持たないため)。
 */
#include <stdint.h>
#include <string.h>

#include "shogi_core.h"

#define NCODE 32
#define NSQ 81

static int32_t BLACK_VALUE[NCODE], WHITE_VALUE[NCODE], HAND_VALUE[7];
/* 重み: 利き・玉の囲い・逃げ道・相手の持ち駒・持ち駒×空きマス(analysis.EvalWeightsの並び) */
static int32_t W_ATTACK, W_SHELTER, W_OPEN, W_HAND, W_HAND_OPEN;
static uint8_t ZONE[NSQ][NSQ]; /* 玉のマス→その隣接マス */
static int zone_ready = 0;

static void build_zones(void)
{
    core_init();
    memset(ZONE, 0, sizeof ZONE);
    for (int sq = 0; sq < NSQ; sq++)
        for (int d = 0; d < 8; d++)
            if (RAY[sq][d][0] >= 0)
                ZONE[sq][RAY[sq][d][0]] = 1;
    zone_ready = 1;
}

void shogi_init(const int32_t *black_value, const int32_t *white_value,
                const int32_t *hand_value, const int32_t *weights)
{
    memcpy(BLACK_VALUE, black_value, sizeof BLACK_VALUE);
    memcpy(WHITE_VALUE, white_value, sizeof WHITE_VALUE);
    memcpy(HAND_VALUE, hand_value, sizeof HAND_VALUE);
    W_ATTACK = weights[0];
    W_SHELTER = weights[1];
    W_OPEN = weights[2];
    W_HAND = weights[3];
    W_HAND_OPEN = weights[4];
    if (!zone_ready)
        build_zones();
}

/* 先手視点のスコア。pieces: 81バイト、hands: 14バイト(先手7種+後手7種)。 */
static int32_t eval_black_raw(const uint8_t *pieces, const uint8_t *hands, int black_king, int white_king)
{
    int32_t black = 0, white = 0, by_black = 0, by_white = 0;
    /* 玉の周囲のマスへ相手の駒が利いているか(index 0: 先手の駒が利く=後手玉側、1: 後手の駒が利く=先手玉側) */
    uint8_t attacked[2][NSQ];
    memset(attacked, 0, sizeof attacked);
    const uint8_t *zone_of_white_king = ZONE[white_king];
    const uint8_t *zone_of_black_king = ZONE[black_king];

    for (int sq = 0; sq < NSQ; sq++) {
        int code = pieces[sq];
        if (code == 0 || code >= NCODE)
            continue;
        int color = code >= PC_WHITE;
        const uint8_t *zone = color ? zone_of_black_king : zone_of_white_king;
        int n = 0;
        if ((code & 15) == PC_KNIGHT) {
            for (int k = 0; k < 2; k++) {
                int t = KNIGHT_TO[color][sq][k];
                if (t >= 0 && zone[t]) {
                    n++;
                    attacked[color][t] = 1;
                }
            }
        }
        for (int d = 0; d < 8; d++) {
            const int8_t *ray = RAY[sq][d];
            if (STEP_DIR[code][d] && ray[0] >= 0 && zone[ray[0]]) {
                n++;
                attacked[color][ray[0]] = 1;
            }
            if (SLIDE_DIR[code][d]) {
                for (int i = 0; i < 8 && ray[i] >= 0; i++) {
                    if (zone[ray[i]]) {
                        n++;
                        attacked[color][ray[i]] = 1;
                    }
                    if (pieces[ray[i]])
                        break;
                }
            }
        }
        if (color) {
            by_white += n;
            white += WHITE_VALUE[code];
        } else {
            by_black += n;
            black += BLACK_VALUE[code];
        }
    }
    for (int i = 0; i < 7; i++) {
        black += hands[i] * HAND_VALUE[i];
        white += hands[7 + i] * HAND_VALUE[i];
    }
    int32_t score = (black - white) + W_ATTACK * (by_black - by_white);
    if (W_SHELTER || W_OPEN || W_HAND || W_HAND_OPEN) {
        /* 玉の危険度の素点(analysis._king_termsと同じ定義)。c=0: 先手玉、1: 後手玉 */
        int32_t shelter[2], open[2], hand[2], hand_open[2];
        for (int c = 0; c < 2; c++) {
            int king = c ? white_king : black_king;
            shelter[c] = open[c] = 0;
            int32_t free_sq = 0;
            for (int sq = 0; sq < NSQ; sq++) {
                if (!ZONE[king][sq])
                    continue;
                int code = pieces[sq];
                if (code && (code >= PC_WHITE) == c) {
                    int kind = code & 15;
                    if (kind == PC_GOLD || kind == PC_SILVER || (kind > PC_PROMOTED + PC_PAWN - 1 && kind <= PC_PROMOTED + PC_SILVER))
                        shelter[c]++;
                    continue;
                }
                free_sq++;
                if (!attacked[1 - c][sq])
                    open[c]++;
            }
            hand[c] = 0;
            for (int i = 1; i < 7; i++)
                hand[c] += hands[(1 - c) * 7 + i];
            hand_open[c] = hand[c] * free_sq;
        }
        score += W_SHELTER * (shelter[0] - shelter[1]) + W_OPEN * (open[0] - open[1])
               + W_HAND * (hand[1] - hand[0]) + W_HAND_OPEN * (hand_open[1] - hand_open[0]);
    }
    return score;
}

int32_t shogi_eval_black(const uint8_t *pieces, const uint8_t *hands, int black_king, int white_king)
{
    return eval_black_raw(pieces, hands, black_king, white_king);
}

int eval_side_to_move(const Pos *pos)
{
    int32_t score = eval_black_raw(pos->board, &pos->hand[0][0], pos->king[BLACK], pos->king[WHITE]);
    return pos->side == BLACK ? score : -score;
}
