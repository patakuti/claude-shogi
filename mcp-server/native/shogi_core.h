/*
 * 将棋の盤面・着手・合法手生成のネイティブ実装(02_design.md §36)。
 *
 * 駒コード・マス番号はcshogi(Python側のboard.pieces)と同じ:
 *   先手 PAWN=1 LANCE=2 KNIGHT=3 SILVER=4 BISHOP=5 ROOK=6 GOLD=7 KING=8
 *        成駒 +PAWN=9 +LANCE=10 +KNIGHT=11 +SILVER=12 +BISHOP=13 +ROOK=14、後手は+16。
 *   マス sq = 筋index*9 + 段index(筋index 0=1筋、段index 0=一段)。先手は段indexが減る向きが前。
 * 持ち駒の並びは 歩・香・桂・銀・金・角・飛 (cshogiのpieces_in_handと同じ)。
 */
#ifndef SHOGI_CORE_H
#define SHOGI_CORE_H

#include <stdint.h>

#define PC_PAWN 1
#define PC_LANCE 2
#define PC_KNIGHT 3
#define PC_SILVER 4
#define PC_BISHOP 5
#define PC_ROOK 6
#define PC_GOLD 7
#define PC_KING 8
#define PC_PROMOTED 8 /* 成駒は駒種+8 (PAWN..ROOK) */
#define PC_WHITE 16

#define BLACK 0
#define WHITE 1

#define MAX_MOVES 600
#define MAX_PLY_UNDO 1024

/* 指し手: to(0-6) | from(7-13、盤上は0..80、打つ駒は81+持ち駒index) | 成(14)
 *         | 取った駒(15-19) | 動かした駒(20-24) */
typedef uint32_t Move;

#define MV_TO(m) ((m) & 127)
#define MV_FROM(m) (((m) >> 7) & 127)
#define MV_PROMO(m) (((m) >> 14) & 1)
#define MV_CAPTURED(m) (((m) >> 15) & 31)
#define MV_PIECE(m) (((m) >> 20) & 31)
#define MV_IS_DROP(m) (MV_FROM(m) >= 81)
#define MV_DROP_INDEX(m) (MV_FROM(m) - 81)

typedef struct {
    uint8_t board[81];
    uint8_t hand[2][7];
    int side;      /* BLACK or WHITE */
    int king[2];   /* 玉のマス */
    uint64_t hash;
    int ply;       /* undoスタックの深さ */
    uint64_t hash_stack[MAX_PLY_UNDO];
} Pos;

void core_init(void);

/* 駒の動きの表(shogi_core.c で生成。評価・探索も参照する)。 */
extern uint8_t STEP_DIR[32][8];    /* 駒コード×方向: 1マス移動できるか */
extern uint8_t SLIDE_DIR[32][8];   /* 駒コード×方向: 走れるか */
extern int8_t RAY[81][8][8];       /* マス×方向: 進むマス列(-1終端) */
extern int8_t KNIGHT_TO[2][81][2]; /* 色×マス: 桂の移動先(-1なし) */
int pos_from_sfen(Pos *pos, const char *sfen);
int pos_to_sfen(const Pos *pos, char *buf, int buflen);
int pos_gen_legal(Pos *pos, Move *out);
int pos_gen_legal_ex(Pos *pos, Move *out, int captures_only); /* captures_only: 取る手のみ(打つ手を除く) */
int pos_has_legal_move(Pos *pos);
int pos_in_check(const Pos *pos);
int pos_attacked(const Pos *pos, int sq, int by_color);
int pos_count_attackers(const Pos *pos, int sq, int by_color);
void pos_make(Pos *pos, Move m);
void pos_unmake(Pos *pos, Move m);
void pos_make_null(Pos *pos);
void pos_unmake_null(Pos *pos);
int move_to_usi(Move m, char *buf);
Move move_from_usi(Pos *pos, const char *usi);
uint64_t pos_perft(Pos *pos, int depth);

/* shogi_eval.c: 材料点+玉の安全度の評価(手番側視点)。shogi_init()で価値表を設定すること。 */
int eval_side_to_move(const Pos *pos);

#endif
