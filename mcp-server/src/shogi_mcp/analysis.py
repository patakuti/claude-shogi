"""Claude思考モード用の局面解析(02_design.md §11)。

盤面はSFENから複製したコピー上でのみ操作し、呼び出し元のBoardは変更しない。
USIエンジンは使わず、詰み探索(cshogi組み込み)と材料点のみの浅い探索で
「頓死・タダ捨て・詰み逃し」を機械的に検出することが目的。
"""

from __future__ import annotations

from typing import Optional

import cshogi
from cshogi import KIF

# 駒割り点数(§11.2)。相対比較にのみ使うため厳密な値である必要はない。
# 成駒は「盤上の働き」で採点する(取られると相手の持ち駒には元の駒として入るが、
# その差はmaterial()が盤・持ち駒を全数集計することで自然に反映される)。
PIECE_VALUES = {
    cshogi.PAWN: 100,
    cshogi.LANCE: 300,
    cshogi.KNIGHT: 350,
    cshogi.SILVER: 500,
    cshogi.GOLD: 550,
    cshogi.BISHOP: 800,
    cshogi.ROOK: 1000,
    cshogi.KING: 0,
    cshogi.PROM_PAWN: 550,
    cshogi.PROM_LANCE: 550,
    cshogi.PROM_KNIGHT: 550,
    cshogi.PROM_SILVER: 550,
    cshogi.PROM_BISHOP: 1000,
    cshogi.PROM_ROOK: 1200,
}
# 持ち駒の並びはcshogi.HAND_PIECES(歩・香・桂・銀・金・角・飛)に対応する。
HAND_PIECE_VALUES = (100, 300, 350, 500, 550, 800, 1000)
HAND_PIECE_NAMES = ("歩", "香", "桂", "銀", "金", "角", "飛")

MATE_SCORE = 100_000
_WHITE_OFFSET = 16  # board.pieces上の後手駒は駒種+16

DEFAULT_SEARCH_DEPTH = 3
DEFAULT_NODE_LIMIT = 300_000
DEFAULT_MATE_PLY = 5


def _copy_board(board: cshogi.Board) -> cshogi.Board:
    return cshogi.Board(board.sfen())


def material(board: cshogi.Board) -> tuple[int, int]:
    """盤上+持ち駒の材料点を(先手, 後手)で返す。"""
    black = white = 0
    for code in board.pieces:
        if code == 0:
            continue
        value = PIECE_VALUES[code % _WHITE_OFFSET]
        if code < _WHITE_OFFSET:
            black += value
        else:
            white += value
    hand_black, hand_white = board.pieces_in_hand
    black += sum(n * v for n, v in zip(hand_black, HAND_PIECE_VALUES))
    white += sum(n * v for n, v in zip(hand_white, HAND_PIECE_VALUES))
    return black, white


def _eval_for_side_to_move(board: cshogi.Board) -> int:
    black, white = material(board)
    return black - white if board.turn == cshogi.BLACK else white - black


def find_mate(board: cshogi.Board, max_ply: int = 7) -> Optional[tuple[int, int]]:
    """手番側から相手玉への詰みを探す。見つかれば(初手のmove, 手数上限)を返す。

    cshogiのmate_move(ply)はply手以内の詰みを探すため、返す手数は「以下」の意味。
    """
    move = board.mate_move_in_1ply()
    if move:
        return move, 1
    ply = 3
    while ply <= max_ply:
        move = board.mate_move(ply)
        if move:
            return move, ply
        ply += 2
    return None


def find_mate_threat(board: cshogi.Board, max_ply: int = DEFAULT_MATE_PLY) -> Optional[tuple[int, int]]:
    """詰めろ検出: 手番側がパスした場合に相手から詰みがあるかを返す。

    王手中はpush_passが不正(実測でAssertionError)のためNoneを返す。
    呼び出し元は王手中かどうかをin_checkで別途判断すること。
    """
    if board.is_check():
        return None
    board.push_pass()
    try:
        if board.is_game_over():
            return None
        return find_mate(board, max_ply)
    finally:
        board.pop_pass()


class _Searcher:
    """材料点のみを評価とするネガマックス+アルファベータ+取る手の静止探索。"""

    def __init__(self, board: cshogi.Board, node_limit: int):
        self.board = board
        self.node_limit = node_limit
        self.nodes = 0
        self.truncated = False

    def _over_budget(self) -> bool:
        self.nodes += 1
        if self.nodes > self.node_limit:
            self.truncated = True
            return True
        return False

    @staticmethod
    def _order_moves(moves: list[int]) -> list[int]:
        """取る手を「取る駒の価値が高い順・取りに行く駒が安い順」(MVV-LVA)で先頭に置く。"""

        def key(m: int) -> tuple[int, int]:
            cap = cshogi.move_cap(m)
            if cap == 0:
                return (1, 0)
            victim = PIECE_VALUES[cap % _WHITE_OFFSET]
            attacker = PIECE_VALUES[cshogi.move_from_piece_type(m)]
            return (0, -(victim * 16 - attacker))

        return sorted(moves, key=key)

    def quiesce(self, alpha: int, beta: int) -> tuple[int, list[int]]:
        if self._over_budget():
            return _eval_for_side_to_move(self.board), []

        if self.board.is_check():
            # 王手中はパス(stand pat)できない。全ての受けを読む。
            moves = list(self.board.legal_moves)
            if not moves:
                return -MATE_SCORE, []
            best_score = -MATE_SCORE
        else:
            stand_pat = _eval_for_side_to_move(self.board)
            if stand_pat >= beta:
                return stand_pat, []
            alpha = max(alpha, stand_pat)
            moves = [m for m in self.board.legal_moves if cshogi.move_cap(m) != 0]
            best_score = stand_pat

        best_pv: list[int] = []
        for m in self._order_moves(moves):
            self.board.push(m)
            score, pv = self.quiesce(-beta, -alpha)
            score = -score
            self.board.pop()
            if score > best_score:
                best_score = score
                best_pv = [m] + pv
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best_score, best_pv

    def search(self, depth: int, alpha: int, beta: int) -> tuple[int, list[int]]:
        if self._over_budget():
            return _eval_for_side_to_move(self.board), []
        moves = list(self.board.legal_moves)
        if not moves:
            return -MATE_SCORE, []  # 手番側の詰み
        if depth <= 0:
            self.nodes -= 1  # quiesce側で数え直す
            return self.quiesce(alpha, beta)

        best_score = -MATE_SCORE - 1
        best_pv: list[int] = []
        for m in self._order_moves(moves):
            self.board.push(m)
            score, pv = self.search(depth - 1, -beta, -alpha)
            score = -score
            self.board.pop()
            if score > best_score:
                best_score = score
                best_pv = [m] + pv
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best_score, best_pv


def search_material(
    board: cshogi.Board,
    depth: int = DEFAULT_SEARCH_DEPTH,
    node_limit: int = DEFAULT_NODE_LIMIT,
) -> dict:
    """現局面を手番側視点で浅く読み、材料点の見通しとPVを返す。盤面は変更しない。"""
    copy = _copy_board(board)
    searcher = _Searcher(copy, node_limit)
    score, pv = searcher.search(depth, -MATE_SCORE - 1, MATE_SCORE + 1)
    return {
        "score": score,
        "pv_usi": [cshogi.move_to_usi(m) for m in pv],
        "nodes": searcher.nodes,
        "truncated": searcher.truncated,
    }


def analyze(board: cshogi.Board, mate_ply: int = 7, threat_ply: int = DEFAULT_MATE_PLY) -> dict:
    """局面の構造化要約(§11.3 analyze_position)。盤面は変更しない。"""
    copy = _copy_board(board)
    black, white = material(copy)
    hand_black, hand_white = copy.pieces_in_hand

    mate = None
    if not copy.is_game_over():
        found = find_mate(copy, mate_ply)
        if found is not None:
            move, ply = found
            mate = {"found": True, "within_ply": ply, "first_move_usi": cshogi.move_to_usi(move)}

    in_check = copy.is_check()
    threat = None
    threat_skipped = in_check
    if not in_check and not copy.is_game_over():
        found = find_mate_threat(copy, threat_ply)
        if found is not None:
            move, ply = found
            threat = {
                "found": True,
                "within_ply": ply,
                "first_move_usi": cshogi.move_to_usi(move),
            }

    def hand_dict(counts) -> dict:
        return {name: n for name, n in zip(HAND_PIECE_NAMES, counts) if n > 0}

    return {
        "material": {"black": black, "white": white, "diff_black_minus_white": black - white},
        "hands": {"black": hand_dict(hand_black), "white": hand_dict(hand_white)},
        "in_check": in_check,
        "mate_for_side_to_move": mate,
        "mate_threat_against_side_to_move": threat,
        "mate_threat_skipped_due_to_check": threat_skipped,
    }


def verify_moves(
    board: cshogi.Board,
    usi_moves: list[str],
    depth: int = DEFAULT_SEARCH_DEPTH,
    node_limit: int = DEFAULT_NODE_LIMIT,
    mate_ply: int = DEFAULT_MATE_PLY,
) -> list[dict]:
    """候補手ごとの機械検証(§11.3 verify_moves)。盤面は変更しない。

    material_changeは「この手を指した後、双方が材料点上の最善を尽くした場合の
    手番側(=この手を指す側)の材料点変化」。負なら駒損が見込まれる。
    """
    results = []
    for usi in usi_moves:
        copy = _copy_board(board)
        move = copy.move_from_usi(usi)
        if move == 0 or not copy.is_legal(move):
            results.append({"usi": usi, "legal": False})
            continue

        baseline = _eval_for_side_to_move(copy)
        copy.push(move)

        entry: dict = {"usi": usi, "legal": True, "captures": None}
        cap = cshogi.move_cap(move)
        if cap != 0:
            entry["captures"] = HAND_PIECE_NAMES[
                (cshogi.PAWN, cshogi.LANCE, cshogi.KNIGHT, cshogi.SILVER,
                 cshogi.GOLD, cshogi.BISHOP, cshogi.ROOK).index(
                    _unpromoted(cap % _WHITE_OFFSET)
                )
            ]

        if copy.is_game_over():
            entry["is_mate"] = True
            entry["gives_check"] = True
            entry["allows_mate"] = None
            entry["material_change"] = 0
            entry["reply_pv_usi"] = []
            results.append(entry)
            continue

        entry["is_mate"] = False
        entry["gives_check"] = copy.is_check()

        allows = find_mate(copy, mate_ply)
        if allows is not None:
            reply, ply = allows
            entry["allows_mate"] = {"within_ply": ply, "first_move_usi": cshogi.move_to_usi(reply)}
        else:
            entry["allows_mate"] = None

        searcher = _Searcher(copy, node_limit)
        score, pv = searcher.search(depth, -MATE_SCORE - 1, MATE_SCORE + 1)
        entry["material_change"] = -score - baseline
        entry["reply_pv_usi"] = [cshogi.move_to_usi(m) for m in pv]
        entry["search_truncated"] = searcher.truncated
        results.append(entry)
    return results


def _unpromoted(piece_type: int) -> int:
    if piece_type in (cshogi.PROM_PAWN,):
        return cshogi.PAWN
    if piece_type == cshogi.PROM_LANCE:
        return cshogi.LANCE
    if piece_type == cshogi.PROM_KNIGHT:
        return cshogi.KNIGHT
    if piece_type == cshogi.PROM_SILVER:
        return cshogi.SILVER
    if piece_type == cshogi.PROM_BISHOP:
        return cshogi.BISHOP
    if piece_type == cshogi.PROM_ROOK:
        return cshogi.ROOK
    return piece_type


def simulate_line(board: cshogi.Board, usi_moves: list[str]) -> dict:
    """読み筋を盤のコピーへ順に適用する(§11.3 simulate_line)。盤面は変更しない。"""
    copy = _copy_board(board)
    start_black, start_white = material(copy)
    applied: list[str] = []
    illegal = None
    for i, usi in enumerate(usi_moves):
        move = copy.move_from_usi(usi)
        if move == 0 or not copy.is_legal(move):
            illegal = {"index": i, "usi": usi}
            break
        copy.push(move)
        applied.append(usi)

    end_black, end_white = material(copy)
    return {
        "applied": applied,
        "illegal_move": illegal,
        "sfen": copy.sfen(),
        "board": KIF.board_to_bod(copy),
        "turn": "black" if copy.turn == cshogi.BLACK else "white",
        "in_check": copy.is_check(),
        "no_legal_moves": copy.is_game_over(),
        "material_change": {
            "black": end_black - start_black,
            "white": end_white - start_white,
        },
    }
