/*
 * 浅い探索(材料点+玉の安全度)のネイティブ実装(02_design.md §37)。
 * analysis.py の _Searcher(§35)と同じアルゴリズム: 反復深化の1反復分の探索、置換表、
 * PVS、null move、LMR、futility、王手延長、静止探索の枝刈り、キラー・ヒストリ。
 * 詰みスコアは±MATE固定(手数を含めない)、ノード数の数え方・打ち切りの扱いもPython版と同じ。
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "shogi_core.h"

#define MATE_SCORE 100000
#define MAX_PLY 64
#define MAX_PV 64
#define TT_BITS 21

enum { TT_EXACT = 0, TT_LOWER = 1, TT_UPPER = 2 };

/* 無効化フラグ(Python版との同値性検証用。0なら全て有効) */
enum {
    NO_TT_CUTOFF = 1,
    NO_NULL_MOVE = 2,
    NO_LMR = 4,
    NO_FUTILITY = 8,
    NO_QUIESCE_PRUNING = 16,
};

#define NULL_MOVE_MIN_DEPTH 3
#define LMR_MIN_DEPTH 3
#define LMR_FULL_MOVES 3
#define FUTILITY_MARGIN 300
#define DELTA_MARGIN 300

typedef struct {
    uint64_t key;
    int32_t score;
    Move move;
    int8_t depth;
    uint8_t flag;
    uint8_t used;
} TTEntry;

typedef struct {
    TTEntry *tt;
    int32_t history[2][88][81];
    Move killers[MAX_PLY + 1][2];
} Context;

typedef struct {
    Context *ctx;
    Pos pos;
    int64_t nodes, limit;
    int truncated;
    int root_depth;
    int flags;
    Move pv[MAX_PLY + 2][MAX_PV];
    int pv_len[MAX_PLY + 2];
} Search;

static int32_t PIECE_VALUE[16] = {0, 100, 300, 350, 500, 800, 1000, 550, 0, 550, 550, 550, 550, 1000, 1200, 0};
/* PIECE_VALUE は駒種(1..14)→材料点。cshogiの駒種番号順(BISHOP=5, ROOK=6, GOLD=7)。 */

void shogi_search_set_piece_values(const int32_t *values) { memcpy(PIECE_VALUE, values, sizeof PIECE_VALUE); }

Context *shogi_ctx_new(void)
{
    core_init();
    Context *ctx = (Context *)calloc(1, sizeof(Context));
    if (!ctx)
        return NULL;
    ctx->tt = (TTEntry *)calloc((size_t)1 << TT_BITS, sizeof(TTEntry));
    if (!ctx->tt) {
        free(ctx);
        return NULL;
    }
    return ctx;
}

void shogi_ctx_free(Context *ctx)
{
    if (!ctx)
        return;
    free(ctx->tt);
    free(ctx);
}

/* 新しい探索(rank_moves の候補手1つ)の開始時にキラーを消す。置換表とヒストリは共有する。 */
void shogi_ctx_new_search(Context *ctx) { memset(ctx->killers, 0, sizeof ctx->killers); }

static int piece_value(int code) { return PIECE_VALUE[code & 15]; }

static int over_budget(Search *s)
{
    s->nodes++;
    if (s->nodes > s->limit) {
        s->truncated = 1;
        return 1;
    }
    return 0;
}

/* 取る手の並べ替え値(MVV-LVA) */
static int capture_key(Move m) { return piece_value((int)MV_CAPTURED(m)) * 16 - piece_value((int)MV_PIECE(m)); }

static void set_pv(Search *s, int ply, Move m)
{
    s->pv[ply][0] = m;
    int n = s->pv_len[ply + 1];
    if (n > MAX_PV - 1)
        n = MAX_PV - 1;
    memcpy(&s->pv[ply][1], s->pv[ply + 1], (size_t)n * sizeof(Move));
    s->pv_len[ply] = n + 1;
}

static int is_capture(Move m) { return MV_CAPTURED(m) != 0; }

/* 取る手を先頭・MVV-LVA順に並べる(静止探索)。王手回避の全手でも取る手を先に。 */
static void order_captures_first(Move *moves, int n)
{
    int keys[MAX_MOVES];
    for (int i = 0; i < n; i++)
        keys[i] = is_capture(moves[i]) ? capture_key(moves[i]) : -(1 << 30);
    for (int i = 0; i < n; i++) {
        int best = i;
        for (int j = i + 1; j < n; j++)
            if (keys[j] > keys[best])
                best = j;
        if (best != i) {
            int tk = keys[i];
            keys[i] = keys[best];
            keys[best] = tk;
            Move tm = moves[i];
            moves[i] = moves[best];
            moves[best] = tm;
        }
    }
}

static int loses_material_by_capture(Search *s, Move m)
{
    Pos *pos = &s->pos;
    int to = (int)MV_TO(m), mover = pos->side, opponent = mover ^ 1;
    if (pos_count_attackers(pos, to, opponent) == 0)
        return 0;
    return pos_count_attackers(pos, to, mover) <= 1;
}

static int quiesce(Search *s, int ply, int alpha, int beta)
{
    Pos *pos = &s->pos;
    s->pv_len[ply] = 0;
    if (over_budget(s))
        return eval_side_to_move(pos);
    if (ply >= MAX_PLY)
        return eval_side_to_move(pos);

    Move moves[MAX_MOVES];
    int n, best, stand_pat = 0, have_stand = 0;
    if (pos_in_check(pos)) {
        n = pos_gen_legal(pos, moves);
        if (n == 0)
            return -MATE_SCORE;
        best = -MATE_SCORE;
    } else {
        stand_pat = eval_side_to_move(pos);
        have_stand = 1;
        if (stand_pat >= beta)
            return stand_pat;
        if (stand_pat > alpha)
            alpha = stand_pat;
        n = pos_gen_legal_ex(pos, moves, 1);
        best = stand_pat;
    }
    order_captures_first(moves, n);

    for (int i = 0; i < n; i++) {
        if (s->truncated)
            break;
        Move m = moves[i];
        if (have_stand && !MV_PROMO(m) && !(s->flags & NO_QUIESCE_PRUNING)) {
            int victim = piece_value((int)MV_CAPTURED(m));
            if (stand_pat + victim + DELTA_MARGIN < alpha)
                continue;
            int attacker = piece_value((int)MV_PIECE(m));
            if (attacker > victim && loses_material_by_capture(s, m))
                continue;
        }
        pos_make(pos, m);
        int score = -quiesce(s, ply + 1, -beta, -alpha);
        pos_unmake(pos, m);
        if (score > best) {
            best = score;
            set_pv(s, ply, m);
        }
        if (score > alpha)
            alpha = score;
        if (alpha >= beta)
            break;
    }
    return best;
}

static int has_non_pawn_material(const Pos *pos)
{
    int side = pos->side;
    for (int i = 1; i < 7; i++)
        if (pos->hand[side][i])
            return 1;
    for (int sq = 0; sq < 81; sq++) {
        int code = pos->board[sq];
        if (code && ((code >= PC_WHITE) == side)) {
            int type = code & 15;
            if (type != PC_PAWN && type != PC_KING)
                return 1;
        }
    }
    return 0;
}

static int history_from(Move m) { return (int)MV_FROM(m); }

/* 手の並べ替え値: 置換表手 > 取る手(MVV-LVA) > キラー > 成り > ヒストリ */
static int64_t move_score(Search *s, Move m, Move tt_move, int ply)
{
    if (m == tt_move)
        return (int64_t)1 << 40;
    if (is_capture(m))
        return ((int64_t)1 << 30) + capture_key(m);
    if (m == s->ctx->killers[ply][0] || m == s->ctx->killers[ply][1])
        return (int64_t)1 << 29;
    int64_t bonus = MV_PROMO(m) ? ((int64_t)1 << 20) : 0;
    return bonus + s->ctx->history[s->pos.side][history_from(m)][MV_TO(m)];
}

static int search(Search *s, int depth, int alpha, int beta, int ply, int allow_null)
{
    Pos *pos = &s->pos;
    s->pv_len[ply] = 0;
    if (over_budget(s))
        return eval_side_to_move(pos);
    int in_check = pos_in_check(pos);
    if (in_check && ply < s->root_depth * 2)
        depth++;
    if (depth <= 0) {
        s->nodes--; /* quiesce側で数え直す */
        return quiesce(s, ply, alpha, beta);
    }
    if (ply >= MAX_PLY - 1)
        return eval_side_to_move(pos);

    int is_pv = beta - alpha > 1;
    uint64_t key = pos->hash;
    TTEntry *slot = &s->ctx->tt[key & (((uint64_t)1 << TT_BITS) - 1)];
    Move tt_move = 0;
    if (slot->used && slot->key == key) {
        tt_move = slot->move;
        if (!is_pv && slot->depth >= depth && !(s->flags & NO_TT_CUTOFF)) {
            int sc = slot->score;
            if (slot->flag == TT_EXACT)
                return sc;
            if (slot->flag == TT_LOWER && sc >= beta)
                return sc;
            if (slot->flag == TT_UPPER && sc <= alpha)
                return sc;
        }
    }

    Move moves[MAX_MOVES];
    int n = pos_gen_legal(pos, moves);
    if (n == 0)
        return -MATE_SCORE;

    int static_eval = 0, have_static = 0;
    if (!in_check && !is_pv) {
        static_eval = eval_side_to_move(pos);
        have_static = 1;
        if (allow_null && !(s->flags & NO_NULL_MOVE) && depth >= NULL_MOVE_MIN_DEPTH && static_eval >= beta &&
            has_non_pawn_material(pos)) {
            int reduction = depth >= 6 ? 3 : 2;
            pos_make_null(pos);
            int score = -search(s, depth - 1 - reduction, -beta, -beta + 1, ply + 1, 0);
            pos_unmake_null(pos);
            if (score >= beta && !s->truncated) {
                s->pv_len[ply] = 0;
                return score >= MATE_SCORE - 1000 ? beta : score;
            }
        }
    }

    /* 手の並べ替え(選択ソートで1手ずつ取り出す) */
    int64_t keys[MAX_MOVES];
    for (int i = 0; i < n; i++)
        keys[i] = move_score(s, moves[i], tt_move, ply);

    int alpha_orig = alpha, best_score = -MATE_SCORE - 1, searched = 0;
    Move best_move = 0;
    for (int i = 0; i < n; i++) {
        int bi = i;
        for (int j = i + 1; j < n; j++)
            if (keys[j] > keys[bi])
                bi = j;
        if (bi != i) {
            int64_t tk = keys[i];
            keys[i] = keys[bi];
            keys[bi] = tk;
            Move tm = moves[i];
            moves[i] = moves[bi];
            moves[bi] = tm;
        }
        if (s->truncated)
            break;
        Move m = moves[i];
        int quiet = !is_capture(m) && !MV_PROMO(m);
        int mover = pos->side;
        pos_make(pos, m);
        int gives_check = pos_in_check(pos);

        if (have_static && quiet && !gives_check && depth <= 2 && searched > 0 && !(s->flags & NO_FUTILITY) &&
            static_eval + FUTILITY_MARGIN * depth <= alpha) {
            pos_unmake(pos, m);
            continue;
        }

        int score;
        if (searched == 0) {
            score = -search(s, depth - 1, -beta, -alpha, ply + 1, 1);
        } else {
            int reduction = 0;
            if (quiet && !in_check && !gives_check && depth >= LMR_MIN_DEPTH && searched >= LMR_FULL_MOVES &&
                !(s->flags & NO_LMR))
                reduction = 1;
            score = -search(s, depth - 1 - reduction, -alpha - 1, -alpha, ply + 1, 1);
            if (score > alpha && reduction)
                score = -search(s, depth - 1, -alpha - 1, -alpha, ply + 1, 1);
            if (alpha < score && score < beta)
                score = -search(s, depth - 1, -beta, -alpha, ply + 1, 1);
        }
        pos_unmake(pos, m);
        searched++;

        if (score > best_score) {
            best_score = score;
            best_move = m;
            set_pv(s, ply, m);
        }
        if (score > alpha)
            alpha = score;
        if (alpha >= beta) {
            if (quiet) {
                Move *k = s->ctx->killers[ply];
                if (k[0] != m) {
                    k[1] = k[0];
                    k[0] = m;
                }
                int32_t *h = &s->ctx->history[mover][history_from(m)][MV_TO(m)];
                *h += depth * depth;
                if (*h > 100000000)
                    *h = 100000000;
            }
            break;
        }
    }

    if (searched == 0) {
        s->pv_len[ply] = 0;
        return have_static ? static_eval : -MATE_SCORE;
    }
    if (!s->truncated) {
        int flag = best_score <= alpha_orig ? TT_UPPER : (best_score >= beta ? TT_LOWER : TT_EXACT);
        if (!slot->used || slot->key != key || slot->depth <= depth) {
            slot->key = key;
            slot->score = best_score;
            slot->move = best_move;
            slot->depth = (int8_t)depth;
            slot->flag = (uint8_t)flag;
            slot->used = 1;
        }
    }
    return best_score;
}

/*
 * sfenの局面を depth で探索する(反復深化の1反復分)。nodes は累積ノード数の入出力。
 * 戻り値はスコア。*truncated は打ち切りの有無。PVはUSI文字列(空白区切り)で pv_out へ。
 * sfenが不正なら -MATE_SCORE*2 を返す。
 */
int shogi_search(Context *ctx, const char *sfen, int depth, int alpha, int beta, int64_t node_limit,
                 int64_t *nodes, int *truncated, int flags, char *pv_out, int pv_out_len)
{
    static Search s; /* 大きいので静的領域に置く(スレッド非対応) */
    memset(&s.pv_len, 0, sizeof s.pv_len);
    s.ctx = ctx;
    if (pos_from_sfen(&s.pos, sfen) != 0)
        return -MATE_SCORE * 2;
    s.nodes = *nodes;
    s.limit = node_limit;
    s.truncated = *truncated;
    s.root_depth = depth;
    s.flags = flags;
    int score = search(&s, depth, alpha, beta, 0, 1);
    *nodes = s.nodes;
    *truncated = s.truncated;

    int len = 0;
    pv_out[0] = 0;
    for (int i = 0; i < s.pv_len[0]; i++) {
        char buf[8];
        int l = move_to_usi(s.pv[0][i], buf);
        if (len + l + 2 > pv_out_len)
            break;
        memcpy(pv_out + len, buf, (size_t)l);
        len += l;
        pv_out[len++] = ' ';
    }
    pv_out[len] = 0;
    return score;
}
