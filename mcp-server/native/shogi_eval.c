/*
 * 浅い探索用の評価関数(材料点 + 玉の安全度)のネイティブ実装。
 * analysis.py の _eval_for_side_to_move と同じ値を返す(02_design.md §34)。
 *
 * 利き表・玉周囲・駒価値表は Python 側が生成して shogi_init() で渡す。
 * ここは表引きと加算のループのみで、利きの定義は持たない。
 * 戻り値は先手視点のスコア(手番による符号反転は呼び出し側で行う)。
 */
#include <stdint.h>
#include <string.h>

#define NCODE 32
#define NSQ 81
#define MAX_STEP 8
#define MAX_RAY_DIR 8
#define MAX_RAY_LEN 8
#define WHITE_OFFSET 16

static int8_t STEP[NCODE][NSQ][MAX_STEP];
static int8_t RAY[NCODE][NSQ][MAX_RAY_DIR][MAX_RAY_LEN];
static uint8_t ZONE[NSQ][NSQ];
static int32_t BLACK_VALUE[NCODE], WHITE_VALUE[NCODE], HAND_VALUE[7];

void shogi_init(const int8_t *step, const int8_t *ray, const uint8_t *zone,
                const int32_t *black_value, const int32_t *white_value,
                const int32_t *hand_value)
{
    memcpy(STEP, step, sizeof STEP);
    memcpy(RAY, ray, sizeof RAY);
    memcpy(ZONE, zone, sizeof ZONE);
    memcpy(BLACK_VALUE, black_value, sizeof BLACK_VALUE);
    memcpy(WHITE_VALUE, white_value, sizeof WHITE_VALUE);
    memcpy(HAND_VALUE, hand_value, sizeof HAND_VALUE);
}

/* pieces: 81バイト、hands: 14バイト(先手7種+後手7種)。king座標は0..80であること。 */
int32_t shogi_eval_black(const uint8_t *pieces, const uint8_t *hands,
                         int black_king, int white_king, int weight)
{
    int32_t black = 0, white = 0, by_black = 0, by_white = 0;
    const uint8_t *zone_of_white_king = ZONE[white_king];
    const uint8_t *zone_of_black_king = ZONE[black_king];

    for (int sq = 0; sq < NSQ; sq++) {
        int code = pieces[sq];
        if (code == 0 || code >= NCODE)
            continue;
        const uint8_t *zone = code < WHITE_OFFSET ? zone_of_white_king : zone_of_black_king;
        int n = 0;
        for (int i = 0; i < MAX_STEP; i++) {
            int t = STEP[code][sq][i];
            if (t < 0)
                break;
            n += zone[t];
        }
        for (int d = 0; d < MAX_RAY_DIR; d++) {
            for (int i = 0; i < MAX_RAY_LEN; i++) {
                int t = RAY[code][sq][d][i];
                if (t < 0)
                    break;
                n += zone[t];
                if (pieces[t])
                    break;
            }
        }
        if (code < WHITE_OFFSET) {
            by_black += n;
            black += BLACK_VALUE[code];
        } else {
            by_white += n;
            white += WHITE_VALUE[code];
        }
    }
    for (int i = 0; i < 7; i++) {
        black += hands[i] * HAND_VALUE[i];
        white += hands[7 + i] * HAND_VALUE[i];
    }
    return (black - white) + weight * (by_black - by_white);
}
