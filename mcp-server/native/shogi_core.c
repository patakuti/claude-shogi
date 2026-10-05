/* 将棋の盤面・着手・合法手生成(02_design.md §36)。型と座標系は shogi_core.h を参照。 */
#include "shogi_core.h"

#include <string.h>

/* 方向: 0=(0,-1) 1=(0,+1) 2=(-1,0) 3=(+1,0) 4=(-1,-1) 5=(+1,+1) 6=(+1,-1) 7=(-1,+1)
 * (筋の差, 段の差)。先手の前は段が減る向き(方向0)。反対方向は d^1。 */
static const int DF[8] = {0, 0, -1, 1, -1, 1, 1, -1};
static const int DR[8] = {-1, 1, 0, 0, -1, 1, -1, 1};
static const int FLIP[8] = {1, 0, 2, 3, 7, 6, 5, 4}; /* 段方向を反転(後手用) */

uint8_t STEP_DIR[32][8];  /* 駒コードごとの1マス移動方向 */
uint8_t SLIDE_DIR[32][8]; /* 駒コードごとの走り方向 */
int8_t RAY[81][8][8];     /* sqから方向dに進むマス列(-1終端) */
int8_t KNIGHT_TO[2][81][2]; /* 色ごとの桂の移動先(-1なし) */
static int8_t KNIGHT_FROM[2][81][2]; /* sqを攻撃する色の桂の位置 */
static const int HAND_TYPE[7] = {PC_PAWN, PC_LANCE, PC_KNIGHT, PC_SILVER, PC_GOLD, PC_BISHOP, PC_ROOK};

static uint64_t Z_PIECE[32][81];
static uint64_t Z_HAND[2][7][19];
static uint64_t Z_SIDE;
static int core_ready = 0;

static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static uint64_t rng(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}

static int on_board(int f, int r) { return f >= 0 && f < 9 && r >= 0 && r < 9; }
static int color_of(int code) { return code >= PC_WHITE ? WHITE : BLACK; }

static void set_dirs(int code, const int *steps, int ns, const int *slides, int nl)
{
    for (int c = 0; c < 2; c++) {
        int pc = code + (c ? PC_WHITE : 0);
        for (int i = 0; i < ns; i++)
            STEP_DIR[pc][c ? FLIP[steps[i]] : steps[i]] = 1;
        for (int i = 0; i < nl; i++)
            SLIDE_DIR[pc][c ? FLIP[slides[i]] : slides[i]] = 1;
    }
}

void core_init(void)
{
    if (core_ready)
        return;
    static const int GOLD_STEPS[6] = {0, 4, 6, 2, 3, 1};
    static const int SILVER_STEPS[5] = {0, 4, 6, 5, 7};
    static const int ALL8[8] = {0, 1, 2, 3, 4, 5, 6, 7};
    static const int ORTH[4] = {0, 1, 2, 3};
    static const int DIAG[4] = {4, 5, 6, 7};
    static const int FWD[1] = {0};

    memset(STEP_DIR, 0, sizeof STEP_DIR);
    memset(SLIDE_DIR, 0, sizeof SLIDE_DIR);
    set_dirs(PC_PAWN, FWD, 1, NULL, 0);
    set_dirs(PC_LANCE, NULL, 0, FWD, 1);
    set_dirs(PC_SILVER, SILVER_STEPS, 5, NULL, 0);
    set_dirs(PC_GOLD, GOLD_STEPS, 6, NULL, 0);
    set_dirs(PC_BISHOP, NULL, 0, DIAG, 4);
    set_dirs(PC_ROOK, NULL, 0, ORTH, 4);
    set_dirs(PC_KING, ALL8, 8, NULL, 0);
    for (int t = PC_PAWN; t <= PC_SILVER; t++)
        if (t != PC_BISHOP && t != PC_ROOK)
            set_dirs(t + PC_PROMOTED, GOLD_STEPS, 6, NULL, 0);
    set_dirs(PC_BISHOP + PC_PROMOTED, ORTH, 4, DIAG, 4);
    set_dirs(PC_ROOK + PC_PROMOTED, DIAG, 4, ORTH, 4);

    memset(RAY, -1, sizeof RAY);
    memset(KNIGHT_TO, -1, sizeof KNIGHT_TO);
    memset(KNIGHT_FROM, -1, sizeof KNIGHT_FROM);
    for (int sq = 0; sq < 81; sq++) {
        int f = sq / 9, r = sq % 9;
        for (int d = 0; d < 8; d++) {
            int n = 0, nf = f + DF[d], nr = r + DR[d];
            while (on_board(nf, nr)) {
                RAY[sq][d][n++] = (int8_t)(nf * 9 + nr);
                nf += DF[d];
                nr += DR[d];
            }
        }
        for (int c = 0; c < 2; c++) {
            int dr = c == BLACK ? -2 : 2, k = 0, j = 0;
            for (int df = -1; df <= 1; df += 2) {
                if (on_board(f + df, r + dr))
                    KNIGHT_TO[c][sq][k++] = (int8_t)((f + df) * 9 + r + dr);
                if (on_board(f + df, r - dr)) /* この桂が来る元のマス */
                    KNIGHT_FROM[c][sq][j++] = (int8_t)((f + df) * 9 + r - dr);
            }
        }
    }
    for (int c = 0; c < 32; c++)
        for (int sq = 0; sq < 81; sq++)
            Z_PIECE[c][sq] = rng();
    for (int c = 0; c < 2; c++)
        for (int t = 0; t < 7; t++)
            for (int n = 0; n < 19; n++)
                Z_HAND[c][t][n] = rng();
    Z_SIDE = rng();
    core_ready = 1;
}

static uint64_t full_hash(const Pos *pos)
{
    uint64_t h = 0;
    for (int sq = 0; sq < 81; sq++)
        if (pos->board[sq])
            h ^= Z_PIECE[pos->board[sq]][sq];
    for (int c = 0; c < 2; c++)
        for (int t = 0; t < 7; t++)
            h ^= Z_HAND[c][t][pos->hand[c][t]];
    if (pos->side == WHITE)
        h ^= Z_SIDE;
    return h;
}

/* ---- SFEN ---- */

static int piece_from_char(char ch)
{
    static const char *letters = "PLNSBRGK"; /* codes 1..8 */
    char up = (ch >= 'a' && ch <= 'z') ? (char)(ch - 'a' + 'A') : ch;
    const char *p = strchr(letters, up);
    if (!p || up == 0)
        return 0;
    int code = (int)(p - letters) + 1;
    return (ch >= 'a' && ch <= 'z') ? code + PC_WHITE : code;
}

int pos_from_sfen(Pos *pos, const char *sfen)
{
    core_init();
    memset(pos, 0, sizeof(Pos));
    pos->king[0] = pos->king[1] = -1;
    int r = 0, col = 0;
    const char *p = sfen;
    for (; *p && *p != ' '; p++) {
        char ch = *p;
        if (ch == '/') {
            r++;
            col = 0;
        } else if (ch >= '1' && ch <= '9') {
            col += ch - '0';
        } else {
            int promoted = 0;
            if (ch == '+') {
                promoted = 1;
                ch = *++p;
            }
            int code = piece_from_char(ch);
            if (!code || r > 8 || col > 8)
                return -1;
            if (promoted)
                code += PC_PROMOTED;
            int sq = (8 - col) * 9 + r;
            pos->board[sq] = (uint8_t)code;
            if ((code & 15) == PC_KING)
                pos->king[color_of(code)] = sq;
            col++;
        }
    }
    if (*p != ' ')
        return -1;
    p++;
    pos->side = (*p == 'w') ? WHITE : BLACK;
    p++;
    while (*p == ' ')
        p++;
    int count = 0;
    for (; *p && *p != ' '; p++) {
        if (*p == '-')
            continue;
        if (*p >= '0' && *p <= '9') {
            count = count * 10 + (*p - '0');
            continue;
        }
        int code = piece_from_char(*p);
        if (!code)
            return -1;
        int type = code & 15, c = color_of(code), idx = -1;
        for (int i = 0; i < 7; i++)
            if (HAND_TYPE[i] == type)
                idx = i;
        if (idx < 0)
            return -1;
        pos->hand[c][idx] = (uint8_t)(count ? count : 1);
        count = 0;
    }
    if (pos->king[0] < 0 || pos->king[1] < 0)
        return -1;
    pos->hash = full_hash(pos);
    return 0;
}

int pos_to_sfen(const Pos *pos, char *buf, int buflen)
{
    static const char *letters = "PLNSBRGK";
    char tmp[256];
    int n = 0;
    for (int r = 0; r < 9; r++) {
        int empty = 0;
        for (int col = 0; col < 9; col++) {
            int code = pos->board[(8 - col) * 9 + r];
            if (!code) {
                empty++;
                continue;
            }
            if (empty) {
                tmp[n++] = (char)('0' + empty);
                empty = 0;
            }
            int type = code & 15;
            if (type > PC_PROMOTED) {
                tmp[n++] = '+';
                type -= PC_PROMOTED;
            }
            char ch = letters[type - 1];
            if (color_of(code) == WHITE)
                ch = (char)(ch - 'A' + 'a');
            tmp[n++] = ch;
        }
        if (empty)
            tmp[n++] = (char)('0' + empty);
        if (r < 8)
            tmp[n++] = '/';
    }
    tmp[n++] = ' ';
    tmp[n++] = pos->side == WHITE ? 'w' : 'b';
    tmp[n++] = ' ';
    /* 持ち駒は 飛・角・金・銀・桂・香・歩 の順(cshogiのsfen()と同じ)、先手→後手 */
    static const int ORDER[7] = {6, 5, 4, 3, 2, 1, 0};
    int any = 0;
    for (int c = 0; c < 2; c++)
        for (int i = 0; i < 7; i++) {
            int idx = ORDER[i], cnt = pos->hand[c][idx];
            if (!cnt)
                continue;
            any = 1;
            if (cnt > 1) {
                if (cnt >= 10)
                    tmp[n++] = (char)('0' + cnt / 10);
                tmp[n++] = (char)('0' + cnt % 10);
            }
            char ch = letters[HAND_TYPE[idx] - 1];
            tmp[n++] = c ? (char)(ch - 'A' + 'a') : ch;
        }
    if (!any)
        tmp[n++] = '-';
    tmp[n++] = ' ';
    tmp[n++] = '1';
    tmp[n] = 0;
    if (n + 1 > buflen)
        return -1;
    memcpy(buf, tmp, (size_t)n + 1);
    return n;
}

/* ---- 利き ---- */

/* sqが by_color の駒に利かれているか。 */
int pos_attacked(const Pos *pos, int sq, int by_color)
{
    for (int d = 0; d < 8; d++) {
        const int8_t *ray = RAY[sq][d];
        for (int i = 0; i < 8 && ray[i] >= 0; i++) {
            int code = pos->board[ray[i]];
            if (!code)
                continue;
            if (color_of(code) == by_color) {
                int opp = d ^ 1; /* その駒がsqへ向かう方向 */
                if (SLIDE_DIR[code][opp] || (i == 0 && STEP_DIR[code][opp]))
                    return 1;
            }
            break;
        }
    }
    int knight = PC_KNIGHT + (by_color ? PC_WHITE : 0);
    for (int k = 0; k < 2; k++) {
        int from = KNIGHT_FROM[by_color][sq][k];
        if (from >= 0 && pos->board[from] == knight)
            return 1;
    }
    return 0;
}

/* sqに利いている by_color の駒の数(ピン・王手放置は考慮しない)。 */
int pos_count_attackers(const Pos *pos, int sq, int by_color)
{
    int count = 0;
    for (int d = 0; d < 8; d++) {
        const int8_t *ray = RAY[sq][d];
        for (int i = 0; i < 8 && ray[i] >= 0; i++) {
            int code = pos->board[ray[i]];
            if (!code)
                continue;
            if (color_of(code) == by_color) {
                int opp = d ^ 1;
                if (SLIDE_DIR[code][opp] || (i == 0 && STEP_DIR[code][opp]))
                    count++;
            }
            break;
        }
    }
    int knight = PC_KNIGHT + (by_color ? PC_WHITE : 0);
    for (int k = 0; k < 2; k++) {
        int from = KNIGHT_FROM[by_color][sq][k];
        if (from >= 0 && pos->board[from] == knight)
            count++;
    }
    return count;
}

int pos_in_check(const Pos *pos) { return pos_attacked(pos, pos->king[pos->side], pos->side ^ 1); }

/* ---- 着手 ---- */

static int hand_index_of(int type)
{
    for (int i = 0; i < 7; i++)
        if (HAND_TYPE[i] == type)
            return i;
    return -1;
}

void pos_make(Pos *pos, Move m)
{
    pos->hash_stack[pos->ply++] = pos->hash;
    int side = pos->side, to = (int)MV_TO(m), from = (int)MV_FROM(m);
    int piece = (int)MV_PIECE(m), cap = (int)MV_CAPTURED(m);
    uint64_t h = pos->hash;
    if (from >= 81) {
        int idx = from - 81;
        h ^= Z_HAND[side][idx][pos->hand[side][idx]];
        pos->hand[side][idx]--;
        h ^= Z_HAND[side][idx][pos->hand[side][idx]];
        pos->board[to] = (uint8_t)piece;
        h ^= Z_PIECE[piece][to];
    } else {
        int placed = MV_PROMO(m) ? piece + PC_PROMOTED : piece;
        pos->board[from] = 0;
        h ^= Z_PIECE[piece][from];
        if (cap) {
            h ^= Z_PIECE[cap][to];
            int base = cap & 15;
            if (base > PC_PROMOTED)
                base -= PC_PROMOTED;
            int idx = hand_index_of(base);
            h ^= Z_HAND[side][idx][pos->hand[side][idx]];
            pos->hand[side][idx]++;
            h ^= Z_HAND[side][idx][pos->hand[side][idx]];
        }
        pos->board[to] = (uint8_t)placed;
        h ^= Z_PIECE[placed][to];
        if ((piece & 15) == PC_KING)
            pos->king[side] = to;
    }
    h ^= Z_SIDE;
    pos->side = side ^ 1;
    pos->hash = h;
}

void pos_unmake(Pos *pos, Move m)
{
    int side = pos->side ^ 1, to = (int)MV_TO(m), from = (int)MV_FROM(m);
    int piece = (int)MV_PIECE(m), cap = (int)MV_CAPTURED(m);
    pos->side = side;
    if (from >= 81) {
        pos->board[to] = 0;
        pos->hand[side][from - 81]++;
    } else {
        pos->board[from] = (uint8_t)piece;
        pos->board[to] = (uint8_t)cap;
        if (cap) {
            int base = cap & 15;
            if (base > PC_PROMOTED)
                base -= PC_PROMOTED;
            pos->hand[side][hand_index_of(base)]--;
        }
        if ((piece & 15) == PC_KING)
            pos->king[side] = from;
    }
    pos->hash = pos->hash_stack[--pos->ply];
}

void pos_make_null(Pos *pos)
{
    pos->hash_stack[pos->ply++] = pos->hash;
    pos->side ^= 1;
    pos->hash ^= Z_SIDE;
}

void pos_unmake_null(Pos *pos)
{
    pos->side ^= 1;
    pos->hash = pos->hash_stack[--pos->ply];
}

/* ---- 合法手生成 ---- */

static Move mk(int piece, int from, int to, int cap, int promo)
{
    return (Move)to | ((Move)from << 7) | ((Move)promo << 14) | ((Move)cap << 15) | ((Move)piece << 20);
}

/* 最奥段から数えた段(0=最奥)。先手は段index、後手は8-段index。 */
static int depth_from_far_rank(int color, int r) { return color == BLACK ? r : 8 - r; }
static int in_zone(int color, int r) { return depth_from_far_rank(color, r) <= 2; }

/* 疑似合法手(自玉の王手放置・打ち歩詰めは未判定)を生成する。 */
static int gen_pseudo(const Pos *pos, Move *out, int captures_only, const uint8_t *evasion)
{
    int side = pos->side, n = 0;
    for (int from = 0; from < 81; from++) {
        int code = pos->board[from];
        if (!code || color_of(code) != side)
            continue;
        int type = code & 15, f = from / 9, r = from % 9;
        int can_promote_piece = type >= PC_PAWN && type <= PC_ROOK && type != PC_GOLD && type != PC_KING;
        /* 各移動先について、成り・不成を追加する */
#define ADD_MOVE(to_sq)                                                                         \
    do {                                                                                        \
        int to_ = (to_sq), tcode = pos->board[to_];                                             \
        if (tcode ? color_of(tcode) == side : captures_only)                                    \
            break;                                                                              \
        if (evasion && type != PC_KING && !evasion[to_])                                        \
            break;                                                                              \
        int tr_ = to_ % 9, promo_ok = can_promote_piece && (in_zone(side, r) || in_zone(side, tr_)); \
        int far_ = depth_from_far_rank(side, tr_), dead = 0;                                    \
        if ((type == PC_PAWN || type == PC_LANCE) && far_ == 0)                                 \
            dead = 1;                                                                           \
        if (type == PC_KNIGHT && far_ <= 1)                                                     \
            dead = 1;                                                                           \
        if (!dead)                                                                              \
            out[n++] = mk(code, from, to_, tcode, 0);                                           \
        if (promo_ok)                                                                           \
            out[n++] = mk(code, from, to_, tcode, 1);                                           \
    } while (0)
        if (type == PC_KNIGHT) {
            for (int k = 0; k < 2; k++) {
                int to = KNIGHT_TO[side][from][k];
                if (to >= 0)
                    ADD_MOVE(to);
            }
            continue;
        }
        for (int d = 0; d < 8; d++) {
            const int8_t *ray = RAY[from][d];
            if (STEP_DIR[code][d] && ray[0] >= 0)
                ADD_MOVE(ray[0]);
            if (SLIDE_DIR[code][d]) {
                for (int i = 0; i < 8 && ray[i] >= 0; i++) {
                    ADD_MOVE(ray[i]);
                    if (pos->board[ray[i]])
                        break;
                }
            }
        }
        (void)f;
#undef ADD_MOVE
    }
    /* 打つ手 */
    for (int idx = 0; idx < 7 && !captures_only; idx++) {
        if (!pos->hand[side][idx])
            continue;
        int type = HAND_TYPE[idx], piece = type + (side ? PC_WHITE : 0);
        for (int to = 0; to < 81; to++) {
            if (pos->board[to] || (evasion && !evasion[to]))
                continue;
            int far = depth_from_far_rank(side, to % 9);
            if ((type == PC_PAWN || type == PC_LANCE) && far == 0)
                continue;
            if (type == PC_KNIGHT && far <= 1)
                continue;
            if (type == PC_PAWN) { /* 二歩 */
                int f = to / 9, dup = 0;
                for (int r = 0; r < 9; r++)
                    if (pos->board[f * 9 + r] == piece)
                        dup = 1;
                if (dup)
                    continue;
            }
            out[n++] = mk(piece, 81 + idx, to, 0, 0);
        }
    }
    return n;
}

static int is_pawn_drop(Move m) { return MV_IS_DROP(m) && (MV_PIECE(m) & 15) == PC_PAWN; }

/* 王手されている場合に1を返し、王手を外せる非玉の手の到達先(王手駒を取るか、間に入るマス)を
 * mask[]に立てる。両王手なら空(玉の移動だけが合法)。 */
static int evasion_mask(const Pos *pos, uint8_t *mask)
{
    int side = pos->side, king = pos->king[side], by = side ^ 1, checkers = 0;
    int checker_sq = -1, checker_dir = -1;
    for (int d = 0; d < 8; d++) {
        const int8_t *ray = RAY[king][d];
        for (int i = 0; i < 8 && ray[i] >= 0; i++) {
            int code = pos->board[ray[i]];
            if (!code)
                continue;
            if (color_of(code) == by) {
                int opp = d ^ 1;
                if (SLIDE_DIR[code][opp] || (i == 0 && STEP_DIR[code][opp])) {
                    checkers++;
                    checker_sq = ray[i];
                    checker_dir = (i == 0 || !SLIDE_DIR[code][opp]) ? -1 : d;
                }
            }
            break;
        }
    }
    int knight = PC_KNIGHT + (by ? PC_WHITE : 0);
    for (int k = 0; k < 2; k++) {
        int from = KNIGHT_FROM[by][king][k];
        if (from >= 0 && pos->board[from] == knight) {
            checkers++;
            checker_sq = from;
            checker_dir = -1;
        }
    }
    if (checkers == 0)
        return 0;
    memset(mask, 0, 81);
    if (checkers == 1) {
        mask[checker_sq] = 1;
        if (checker_dir >= 0) {
            const int8_t *ray = RAY[king][checker_dir];
            for (int i = 0; i < 8 && ray[i] >= 0 && ray[i] != checker_sq; i++)
                mask[ray[i]] = 1;
        }
    }
    return 1;
}

/* 王手されていないとき、動かすと自玉が取られる(ピンされている)自駒のマスを pinned[] に立てる。 */
static void find_pinned(const Pos *pos, uint8_t *pinned)
{
    int side = pos->side, king = pos->king[side];
    memset(pinned, 0, 81);
    for (int d = 0; d < 8; d++) {
        const int8_t *ray = RAY[king][d];
        int candidate = -1;
        for (int i = 0; i < 8 && ray[i] >= 0; i++) {
            int code = pos->board[ray[i]];
            if (!code)
                continue;
            if (candidate < 0) {
                if (color_of(code) != side)
                    break; /* 最初に当たったのが敵駒なら、挟む自駒はない */
                candidate = ray[i];
            } else {
                if (color_of(code) != side && SLIDE_DIR[code][d ^ 1])
                    pinned[candidate] = 1;
                break;
            }
        }
    }
}

/* 打つ歩が相手玉に王手をかけるか(歩の利きの先が相手玉)。 */
static int pawn_drop_gives_check(const Pos *pos, Move m)
{
    int to = (int)MV_TO(m), side = pos->side;
    int target = side == BLACK ? to % 9 - 1 : to % 9 + 1;
    return target >= 0 && target < 9 && (to / 9) * 9 + target == pos->king[side ^ 1];
}

/* 手mを指した後、自玉が取られず、打ち歩詰めでもないか。posは一時的に変更して戻す。 */
static int legal_after(Pos *pos, Move m)
{
    int side = pos->side;
    pos_make(pos, m);
    int ok = !pos_attacked(pos, pos->king[side], side ^ 1);
    if (ok && is_pawn_drop(m) && pos_in_check(pos) && !pos_has_legal_move(pos))
        ok = 0; /* 打ち歩詰め */
    pos_unmake(pos, m);
    return ok;
}

/* 疑似合法手のうち、合法なものだけを out に詰める。王手されていない場合、ピンされていない
 * 駒の移動と打つ手は自玉を危険にしないため、着手による確認を省く(王手がけの歩打ちのみ
 * 打ち歩詰めを確認する)。 */
static int filter_legal(Pos *pos, const Move *pseudo, int n, Move *out, int in_check)
{
    int k = 0;
    uint8_t pinned[81];
    if (!in_check)
        find_pinned(pos, pinned);
    for (int i = 0; i < n; i++) {
        Move m = pseudo[i];
        int safe = 0;
        if (!in_check) {
            if (MV_IS_DROP(m))
                safe = !(is_pawn_drop(m) && pawn_drop_gives_check(pos, m));
            else
                safe = (MV_PIECE(m) & 15) != PC_KING && !pinned[MV_FROM(m)];
        }
        if (safe || legal_after(pos, m))
            out[k++] = m;
    }
    return k;
}

int pos_gen_legal_ex(Pos *pos, Move *out, int captures_only)
{
    Move pseudo[MAX_MOVES];
    uint8_t mask[81];
    int in_check = evasion_mask(pos, mask);
    int n = gen_pseudo(pos, pseudo, captures_only, in_check ? mask : NULL);
    return filter_legal(pos, pseudo, n, out, in_check);
}

int pos_gen_legal(Pos *pos, Move *out) { return pos_gen_legal_ex(pos, out, 0); }

int pos_has_legal_move(Pos *pos)
{
    Move pseudo[MAX_MOVES], legal[MAX_MOVES];
    uint8_t mask[81];
    int in_check = evasion_mask(pos, mask);
    int n = gen_pseudo(pos, pseudo, 0, in_check ? mask : NULL);
    return filter_legal(pos, pseudo, n, legal, in_check) > 0;
}

/* ---- USI / perft ---- */

int move_to_usi(Move m, char *buf)
{
    int to = (int)MV_TO(m), n = 0;
    if (MV_IS_DROP(m)) {
        static const char *letters = "PLNSBRGK";
        buf[n++] = letters[HAND_TYPE[MV_DROP_INDEX(m)] - 1];
        buf[n++] = '*';
    } else {
        int from = (int)MV_FROM(m);
        buf[n++] = (char)('1' + from / 9);
        buf[n++] = (char)('a' + from % 9);
    }
    buf[n++] = (char)('1' + to / 9);
    buf[n++] = (char)('a' + to % 9);
    if (MV_PROMO(m))
        buf[n++] = '+';
    buf[n] = 0;
    return n;
}

/* USI文字列に対応する合法手を返す。なければ0。 */
Move move_from_usi(Pos *pos, const char *usi)
{
    Move moves[MAX_MOVES];
    int n = pos_gen_legal(pos, moves);
    char buf[8];
    for (int i = 0; i < n; i++) {
        move_to_usi(moves[i], buf);
        if (strcmp(buf, usi) == 0)
            return moves[i];
    }
    return 0;
}

uint64_t pos_perft(Pos *pos, int depth)
{
    Move moves[MAX_MOVES];
    int n = pos_gen_legal(pos, moves);
    if (depth <= 1)
        return (uint64_t)n;
    uint64_t total = 0;
    for (int i = 0; i < n; i++) {
        pos_make(pos, moves[i]);
        total += pos_perft(pos, depth - 1);
        pos_unmake(pos, moves[i]);
    }
    return total;
}

/* ---- テスト用の公開API(ctypes) ---- */

/* sfenの合法手をUSI文字列(空白区切り)で out に書く。戻り値は手数(失敗は-1)。 */
int shogi_core_legal_moves(const char *sfen, char *out, int outlen)
{
    Pos pos;
    Move moves[MAX_MOVES];
    if (pos_from_sfen(&pos, sfen) != 0)
        return -1;
    int n = pos_gen_legal(&pos, moves), len = 0;
    char buf[8];
    for (int i = 0; i < n; i++) {
        int l = move_to_usi(moves[i], buf);
        if (len + l + 2 > outlen)
            return -1;
        memcpy(out + len, buf, (size_t)l);
        len += l;
        out[len++] = ' ';
    }
    out[len] = 0;
    return n;
}

int64_t shogi_core_perft(const char *sfen, int depth)
{
    Pos pos;
    if (pos_from_sfen(&pos, sfen) != 0)
        return -1;
    return (int64_t)pos_perft(&pos, depth);
}

/* sfenにUSI手順(空白区切り)を適用した局面のSFENを out に書く。非合法手があれば-1。 */
int shogi_core_apply(const char *sfen, const char *usi_moves, char *out, int outlen)
{
    Pos pos;
    if (pos_from_sfen(&pos, sfen) != 0)
        return -1;
    char word[16];
    const char *p = usi_moves;
    while (*p) {
        while (*p == ' ')
            p++;
        int l = 0;
        while (*p && *p != ' ' && l < 15)
            word[l++] = *p++;
        word[l] = 0;
        if (!l)
            break;
        Move m = move_from_usi(&pos, word);
        if (!m)
            return -1;
        pos_make(&pos, m);
    }
    return pos_to_sfen(&pos, out, outlen);
}
