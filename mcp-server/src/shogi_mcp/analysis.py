"""Claude思考モード用の局面解析(02_design.md §11)。

盤面はSFENから複製したコピー上でのみ操作し、呼び出し元のBoardは変更しない。
USIエンジンは使わず、詰み探索(cshogi組み込み)・自前の利き計算(§13.2)・
材料点+玉の安全度の浅い探索で「頓死・タダ捨て・詰み逃し・当たりの見落とし」を
機械的に検出することが目的。
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
PIECE_NAMES = {
    cshogi.PAWN: "歩", cshogi.LANCE: "香", cshogi.KNIGHT: "桂", cshogi.SILVER: "銀",
    cshogi.GOLD: "金", cshogi.BISHOP: "角", cshogi.ROOK: "飛", cshogi.KING: "玉",
    cshogi.PROM_PAWN: "と", cshogi.PROM_LANCE: "成香", cshogi.PROM_KNIGHT: "成桂",
    cshogi.PROM_SILVER: "成銀", cshogi.PROM_BISHOP: "馬", cshogi.PROM_ROOK: "龍",
}
_RANK_KANJI = "一二三四五六七八九"

MATE_SCORE = 100_000
_WHITE_OFFSET = 16  # board.pieces上の後手駒は駒種+16

DEFAULT_SEARCH_DEPTH = 3
# 玉の安全度評価の追加(§13.5)でノード単価が上がったため300k→50kに引き下げ
# (候補5手で数秒以内の要件を維持。上限到達時は静的評価へフォールバック)。
DEFAULT_NODE_LIMIT = 50_000
DEFAULT_MATE_PLY = 5

# 玉の安全度(§13.5): 玉の隣接マスへの相手の利き1つあたりの点数(材料点スケール)。
KING_SAFETY_WEIGHT = 40

# --- 利き計算(§13.2) --------------------------------------------------------
# 座標系: sq = (筋-1)*9 + (段-1)。筋方向は±9、段方向(一→九)は+1(実機確認済み)。
# 判定表は先手(BLACK)の駒が(df, dr)=(筋差, 段差)へ利く形で定義し、後手は段差を反転する。

_GOLD_STEPS = frozenset({(0, -1), (-1, -1), (1, -1), (-1, 0), (1, 0), (0, 1)})
_KING_STEPS = frozenset({(df, dr) for df in (-1, 0, 1) for dr in (-1, 0, 1) if (df, dr) != (0, 0)})
# 1マス利き(走り利きは含めない。馬・龍は走り以外の追加の1マス利きのみ)
_STEP_ATTACKS = {
    cshogi.PAWN: frozenset({(0, -1)}),
    cshogi.KNIGHT: frozenset({(-1, -2), (1, -2)}),
    cshogi.SILVER: frozenset({(0, -1), (-1, -1), (1, -1), (-1, 1), (1, 1)}),
    cshogi.GOLD: _GOLD_STEPS,
    cshogi.KING: _KING_STEPS,
    cshogi.PROM_PAWN: _GOLD_STEPS,
    cshogi.PROM_LANCE: _GOLD_STEPS,
    cshogi.PROM_KNIGHT: _GOLD_STEPS,
    cshogi.PROM_SILVER: _GOLD_STEPS,
    cshogi.PROM_BISHOP: frozenset({(0, -1), (0, 1), (-1, 0), (1, 0)}),
    cshogi.PROM_ROOK: frozenset({(-1, -1), (-1, 1), (1, -1), (1, 1)}),
}
# 走り利き(方向はray単位。香のみ先後で向きが変わる)
_RAY_DIRECTIONS = ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))
_RAY_ATTACKS = {
    cshogi.LANCE: frozenset({(0, -1)}),
    cshogi.BISHOP: frozenset({(-1, -1), (-1, 1), (1, -1), (1, 1)}),
    cshogi.ROOK: frozenset({(0, -1), (0, 1), (-1, 0), (1, 0)}),
    cshogi.PROM_BISHOP: frozenset({(-1, -1), (-1, 1), (1, -1), (1, 1)}),
    cshogi.PROM_ROOK: frozenset({(0, -1), (0, 1), (-1, 0), (1, 0)}),
}
# 探索の全リーフで呼ばれるため、駒コード(先後込み)→利きベクトル集合と、
# マスごとの近接候補・走り経路を起動時に前計算しておく(§13.5の性能対策)。
# ベクトルは (筋差)*10 + (段差) の整数にエンコードする。


def _vec(df: int, dr: int) -> int:
    return df * 10 + dr


def _build_attack_tables():
    step_sets = [frozenset()] * 32
    ray_sets = [frozenset()] * 32
    for piece_type, steps in _STEP_ATTACKS.items():
        step_sets[piece_type] = frozenset(_vec(df, dr) for df, dr in steps)
        step_sets[piece_type + _WHITE_OFFSET] = frozenset(_vec(df, -dr) for df, dr in steps)
    for piece_type, rays in _RAY_ATTACKS.items():
        ray_sets[piece_type] = frozenset(_vec(df, dr) for df, dr in rays)
        ray_sets[piece_type + _WHITE_OFFSET] = frozenset(_vec(df, -dr) for df, dr in rays)

    origin_offsets = tuple(_KING_STEPS | {(-1, -2), (1, -2), (-1, 2), (1, 2)})
    step_origins = []  # sq -> ((origin_sq, 攻撃ベクトル), ...)
    ray_paths = []  # sq -> (((sqの隣から盤端までのマス列), 攻撃ベクトル), ...)
    for sq in range(81):
        tf, tr = divmod(sq, 9)
        origins = []
        for df, dr in origin_offsets:
            of, orank = tf + df, tr + dr
            if 0 <= of <= 8 and 0 <= orank <= 8:
                origins.append((of * 9 + orank, _vec(-df, -dr)))
        step_origins.append(tuple(origins))
        paths = []
        for df, dr in _RAY_DIRECTIONS:
            path = []
            of, orank = tf + df, tr + dr
            while 0 <= of <= 8 and 0 <= orank <= 8:
                path.append(of * 9 + orank)
                of += df
                orank += dr
            if path:
                paths.append((tuple(path), _vec(-df, -dr)))
        ray_paths.append(tuple(paths))
    return step_sets, ray_sets, tuple(step_origins), tuple(ray_paths)


_STEP_SETS, _RAY_SETS, _STEP_ORIGINS, _RAY_PATHS = _build_attack_tables()


def attackers(pieces: list[int], color: int, sq: int) -> list[int]:
    """colorの駒でマスsqに利いているもののマス番号一覧(reverse ray-cast)。

    piecesはboard.pieces(81要素)。sq上の駒自身は含まない。
    ピンや王手放置は考慮しない純粋な利き数(§13.3の仕様)。
    """
    white = color == cshogi.WHITE
    result = []
    for osq, vec in _STEP_ORIGINS[sq]:
        code = pieces[osq]
        if code and (code >= _WHITE_OFFSET) == white and vec in _STEP_SETS[code]:
            result.append(osq)
    for path, vec in _RAY_PATHS[sq]:
        for osq in path:
            code = pieces[osq]
            if code:
                if (code >= _WHITE_OFFSET) == white and vec in _RAY_SETS[code]:
                    result.append(osq)
                break
    return result


def _count_attackers(pieces: list[int], white: bool, sq: int) -> int:
    """attackers()のカウント専用版(評価関数のホットパス用、リストを作らない)。"""
    count = 0
    for osq, vec in _STEP_ORIGINS[sq]:
        code = pieces[osq]
        if code and (code >= _WHITE_OFFSET) == white and vec in _STEP_SETS[code]:
            count += 1
    for path, vec in _RAY_PATHS[sq]:
        for osq in path:
            code = pieces[osq]
            if code:
                if (code >= _WHITE_OFFSET) == white and vec in _RAY_SETS[code]:
                    count += 1
                break
    return count


def square_name(sq: int) -> str:
    """マス番号を「2二」形式の名前にする。"""
    return f"{sq // 9 + 1}{_RANK_KANJI[sq % 9]}"


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


# 玉の隣接8マス(前計算)
_KING_ZONES = tuple(
    tuple(
        (sq // 9 + df) * 9 + (sq % 9 + dr)
        for df, dr in _KING_STEPS
        if 0 <= sq // 9 + df <= 8 and 0 <= sq % 9 + dr <= 8
    )
    for sq in range(81)
)


def _king_danger(pieces: list[int], attacker_is_white: bool, king_sq: int) -> int:
    """玉の隣接マスに対する相手(attacker側)の利き数の合計(§13.5)。"""
    danger = 0
    for zone_sq in _KING_ZONES[king_sq]:
        danger += _count_attackers(pieces, attacker_is_white, zone_sq)
    return danger


def _eval_for_side_to_move(board: cshogi.Board) -> int:
    """材料点差 + 玉の安全度(§13.5)。手番側視点。"""
    pieces = board.pieces
    black = white = 0
    for code in pieces:
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

    safety = KING_SAFETY_WEIGHT * (
        _king_danger(pieces, False, board.king_square(cshogi.WHITE))
        - _king_danger(pieces, True, board.king_square(cshogi.BLACK))
    )
    score = (black - white) + safety
    return score if board.turn == cshogi.BLACK else -score


def _pawn_drop_risk(pieces: list[int], opp_color: int, opp_pawn_count: int, sq: int) -> bool:
    """opp_colorが持ち駒の歩を打ってsqの駒に当てられるか(§15.1)。

    sqから見て相手が前進する方向に1段の打ち込み先が、盤内・空きマス・
    二歩でなく・opp_colorにとっての最終段でもないことを確認する。
    """
    if opp_pawn_count <= 0:
        return False
    file_, rank = divmod(sq, 9)
    origin_rank = rank + 1 if opp_color == cshogi.BLACK else rank - 1
    if not 0 <= origin_rank <= 8:
        return False
    origin_sq = file_ * 9 + origin_rank
    if pieces[origin_sq] != 0:
        return False
    pawn_code = cshogi.PAWN if opp_color == cshogi.BLACK else cshogi.PAWN + _WHITE_OFFSET
    if any(pieces[file_ * 9 + r] == pawn_code for r in range(9)):
        return False
    illegal_rank = 0 if opp_color == cshogi.BLACK else 8
    if origin_rank == illegal_rank:
        return False
    return True


def attacked_pieces(board: cshogi.Board, color: Optional[int] = None) -> list[dict]:
    """colorの駒(玉以外)への当たり一覧(§13.3, §14.1, §15.1)。駒の価値が高い順。

    colorを省略すると従来どおり手番側。ピンや取り合いの手順は考慮しない静的な
    利き数。玉への当たり=王手はin_checkで報告する。盤上の利きに加え、相手の
    持ち駒の歩による当たり(pawn_drop_risk)も判定する(§15.1)。

    紐(defenders)が1つ以上あり、かつその全てが自玉である場合は
    king_only_defense: trueを返す(§19.1)。玉による「防御」は実際に取り返すと
    玉自身が危険な位置に出る特殊なケースであり、他の駒による紐と同列に安全とは
    見なせない。hanging(紐なし)とは排他的な関係(両方trueにはならない)。
    ただし玉が動いた後に実際に安全かどうか(他の駒の利きに新たに入るか)までは
    判定しない。あくまで「紐の内訳が玉のみである」という事実のみを返し、
    最終判断は呼び出し側に委ねる(§13.3の限界を踏襲)。
    """
    pieces = board.pieces
    own_color = board.turn if color is None else color
    opp_color = cshogi.WHITE if own_color == cshogi.BLACK else cshogi.BLACK
    own_is_white = own_color == cshogi.WHITE
    hand_black, hand_white = board.pieces_in_hand
    opp_pawn_count = (hand_black if opp_color == cshogi.BLACK else hand_white)[0]

    result = []
    for sq, code in enumerate(pieces):
        if code == 0 or (code >= _WHITE_OFFSET) != own_is_white:
            continue
        piece_type = code % _WHITE_OFFSET
        if piece_type == cshogi.KING:
            continue
        atk = attackers(pieces, opp_color, sq)
        drop_risk = _pawn_drop_risk(pieces, opp_color, opp_pawn_count, sq)
        if not atk and not drop_risk:
            continue
        defenders = attackers(pieces, own_color, sq)
        king_only_defense = bool(defenders) and all(
            pieces[d] % _WHITE_OFFSET == cshogi.KING for d in defenders
        )
        cheapest = (
            PIECE_NAMES[pieces[min(atk, key=lambda a: PIECE_VALUES[pieces[a] % _WHITE_OFFSET])] % _WHITE_OFFSET]
            if atk else None
        )
        result.append({
            "square": square_name(sq),
            "piece": PIECE_NAMES[piece_type],
            "attackers": len(atk),
            "defenders": len(defenders),
            "hanging": not defenders,
            "king_only_defense": king_only_defense,
            "cheapest_attacker": cheapest,
            "pawn_drop_risk": drop_risk,
            "_value": PIECE_VALUES[piece_type],
        })
    result.sort(key=lambda e: -e["_value"])
    for entry in result:
        del entry["_value"]
    return result


def check_evasions(board: cshogi.Board, threat_ply: int = DEFAULT_MATE_PLY) -> dict:
    """王手中の詰めろ検出(§13.4): 各回避手の後に相手からの詰みが残るかを個別に調べる。

    boardは呼び出し元で複製済みであること(push/popで復元はするが前提として)。
    """
    safe: list[str] = []
    total = 0
    for move in board.legal_moves:
        total += 1
        board.push(move)
        try:
            if find_mate(board, threat_ply) is None:
                safe.append(cshogi.move_to_usi(move))
        finally:
            board.pop()
    return {"total": total, "safe_usi": safe, "all_allow_mate": total > 0 and not safe}


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
    """材料点+玉の安全度を評価とするネガマックス+アルファベータ+取る手の静止探索。"""

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


def _iterative_deepen(searcher: _Searcher, max_depth: int) -> tuple[Optional[int], list[int], int]:
    """反復深化(§14.4): 深さ1からmax_depthまで、ノード予算を共有して順に探索する。

    打ち切りが発生した反復の結果は捨て、直前に完了した深さの結果(スコア・PV)を返す。
    1回も完了しなければ(score=None, pv=[], completed_depth=0)。
    max_depth<=0は深さ0(静止探索のみ)を1回実行する特殊ケース(内部評価用)。
    """
    if max_depth <= 0:
        score, pv = searcher.search(0, -MATE_SCORE - 1, MATE_SCORE + 1)
        return (None, [], 0) if searcher.truncated else (score, pv, 0)

    best_score: Optional[int] = None
    best_pv: list[int] = []
    completed_depth = 0
    for d in range(1, max_depth + 1):
        score, pv = searcher.search(d, -MATE_SCORE - 1, MATE_SCORE + 1)
        if searcher.truncated:
            break
        best_score = score
        best_pv = pv
        completed_depth = d
    return best_score, best_pv, completed_depth


def search_material(
    board: cshogi.Board,
    depth: int = DEFAULT_SEARCH_DEPTH,
    node_limit: int = DEFAULT_NODE_LIMIT,
) -> dict:
    """現局面を手番側視点で浅く読み、評価(材料点+玉の安全度)とPVを返す。盤面は変更しない。

    反復深化(§14.4)で、打ち切られた反復の結果は捨てて直前に完了した深さを採用する。
    """
    copy = _copy_board(board)
    searcher = _Searcher(copy, node_limit)
    score, pv, completed_depth = _iterative_deepen(searcher, depth)
    return {
        "score": score,
        "pv_usi": [cshogi.move_to_usi(m) for m in pv],
        "nodes": searcher.nodes,
        "truncated": searcher.truncated,
        "completed_depth": completed_depth,
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
    evasions = None
    if not copy.is_game_over():
        if in_check:
            # 王手中はパスできないため、全回避手を個別に検証する(§13.4)
            evasions = check_evasions(copy, threat_ply)
        else:
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
        "check_evasions": evasions,
        "attacked_pieces": attacked_pieces(copy),
        "major_piece_drop_threats": major_piece_drop_threats(copy),
        "trapped_major_pieces": trapped_major_pieces(copy),
    }


_MAJOR_PIECE_TYPES = frozenset(
    {cshogi.ROOK, cshogi.BISHOP, cshogi.PROM_ROOK, cshogi.PROM_BISHOP}
)


def _captures_major_piece(moves: list[int]) -> bool:
    """movesのいずれかで飛・角(成りを含む)が捕られていればTrue(§16.1)。"""
    for m in moves:
        cap = cshogi.move_cap(m)
        if cap and (cap % _WHITE_OFFSET) in _MAJOR_PIECE_TYPES:
            return True
    return False


def verify_moves(
    board: cshogi.Board,
    usi_moves: list[str],
    depth: int = DEFAULT_SEARCH_DEPTH,
    node_limit: int = DEFAULT_NODE_LIMIT,
    mate_ply: int = DEFAULT_MATE_PLY,
) -> list[dict]:
    """候補手ごとの機械検証(§11.3 verify_moves)。盤面は変更しない。

    material_changeは「この手を指した後、双方が最善を尽くした場合の
    手番側(=この手を指す側)の材料点変化」。負なら駒損が見込まれる。
    探索の評価には玉の安全度(§13.5)も加味されるが、material_changeは
    読み筋(PV)を適用した局面の実際の材料点差から算出する(純粋な駒得損)。
    探索は反復深化(§14.4)。打ち切られた反復のPVは信用せず、完了した深さが
    0(search_depth_completed == 0)ならmaterial_change/reply_pv_usiは
    信頼できる読みなしとして返す。
    destination/own_attacked_after(§14.3)はis_mateの候補には付けない。
    major_piece_trade(§16.1)は「この手、または読み筋(pv)のどこかで飛・角
    (成りを含む)が捕られるか」を示す真偽値。search_depth_completed == 0の
    場合はpvが空のため候補手自体の捕り駒のみで判定する(読み筋側の将来の
    大駒交換は検出できない)。局面フェーズ(序盤/中盤/終盤)の判定はしない。
    """
    results = []
    for usi in usi_moves:
        copy = _copy_board(board)
        move = copy.move_from_usi(usi)
        if move == 0 or not copy.is_legal(move):
            results.append({"usi": usi, "legal": False})
            continue

        base_black, base_white = material(copy)
        mover_is_black = copy.turn == cshogi.BLACK
        mover_color = cshogi.BLACK if mover_is_black else cshogi.WHITE
        opponent_color = cshogi.WHITE if mover_is_black else cshogi.BLACK
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
            entry["major_piece_trade"] = _captures_major_piece([move])
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

        # §14.3: 着手直後(応手を読む前)の盤面に対する移動先の安全性と自駒への当たり
        to_sq = cshogi.move_to(move)
        pieces_after = copy.pieces
        entry["destination"] = {
            "square": square_name(to_sq),
            "opponent_effects": len(attackers(pieces_after, opponent_color, to_sq)),
            "own_supports": len(attackers(pieces_after, mover_color, to_sq)),
        }
        entry["own_attacked_after"] = attacked_pieces(copy, color=mover_color)[:5]

        searcher = _Searcher(copy, node_limit)
        score, pv, completed_depth = _iterative_deepen(searcher, depth)
        entry["search_depth_completed"] = completed_depth
        entry["search_truncated"] = searcher.truncated
        if completed_depth == 0:
            entry["material_change"] = None
            entry["reply_pv_usi"] = []
            # pvが空(読み筋が信頼できない)なので候補手自体の捕り駒のみで判定する(§16.1)。
            entry["major_piece_trade"] = _captures_major_piece([move])
        else:
            # PVを適用した局面の実材料点差からmaterial_changeを算出(§13.5)
            for m in pv:
                copy.push(m)
            end_black, end_white = material(copy)
            if mover_is_black:
                entry["material_change"] = (end_black - end_white) - (base_black - base_white)
            else:
                entry["material_change"] = (end_white - end_black) - (base_white - base_black)
            entry["reply_pv_usi"] = [cshogi.move_to_usi(m) for m in pv]
            entry["major_piece_trade"] = _captures_major_piece([move] + pv)
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


# --- 大駒打ち込みの脅威検出(§17) --------------------------------------------

_DROP_PIECE_TYPES = {cshogi.ROOK: "R", cshogi.BISHOP: "B"}


def _usi_square(sq: int) -> str:
    file_, rank = divmod(sq, 9)
    return f"{file_ + 1}{chr(ord('a') + rank)}"


def major_piece_drop_threats(board: cshogi.Board) -> list[dict]:
    """自陣後方への安全な大駒打ち込みが、成り込みと組み合わさって王手・両取り・
    安全な当たりに発展する脅威の一覧(§17.1)。boardは手番側(防御側)の局面。
    盤面は変更しない。

    「手番側が2手連続で何もしなかった」場合の脅威を、既存のfind_mate_threat
    (§11.2)と同じくpush_passで仮定して検出する。王手中(push_passが使えない)と、
    打ち込み自体が直接王手になる候補はこの関数の対象外(既存の王手検出・
    回避検証の範疇)。
    """
    if board.is_check():
        return []

    copy = _copy_board(board)
    own_color = copy.turn
    opp_color = cshogi.WHITE if own_color == cshogi.BLACK else cshogi.BLACK
    hand_black, hand_white = copy.pieces_in_hand
    opp_hand = hand_black if opp_color == cshogi.BLACK else hand_white
    drop_piece_types = []
    if opp_hand[6] > 0:  # 飛
        drop_piece_types.append(cshogi.ROOK)
    if opp_hand[5] > 0:  # 角
        drop_piece_types.append(cshogi.BISHOP)
    if not drop_piece_types:
        return []

    pieces = copy.pieces
    back_ranks = (6, 7, 8) if own_color == cshogi.BLACK else (0, 1, 2)
    candidate_squares = [
        sq for sq in range(81)
        if pieces[sq] == 0 and sq % 9 in back_ranks and not attackers(pieces, own_color, sq)
    ]

    results = []
    for sq in candidate_squares:
        for piece_type in drop_piece_types:
            entry = _check_drop_threat(copy, own_color, opp_color, sq, piece_type)
            if entry is not None:
                results.append(entry)
    return results


def _check_drop_threat(
    copy: cshogi.Board, own_color: int, opp_color: int, sq: int, piece_type: int
) -> Optional[dict]:
    """1つの打ち込み候補(マス・駒種)を検証する。呼び出し後、copyは元の局面に復元される。"""
    usi = f"{_DROP_PIECE_TYPES[piece_type]}*{_usi_square(sq)}"
    copy.push_pass()
    try:
        move = copy.move_from_usi(usi)
        if move == 0 or not copy.is_legal(move):
            return None
        copy.push(move)
        try:
            if copy.is_check():
                return None  # 打ち込み自体が王手(既存の王手検出の範疇のため対象外)
            copy.push_pass()
            try:
                return _find_followup_threat(copy, own_color, opp_color, sq, piece_type)
            finally:
                copy.pop_pass()
        finally:
            copy.pop()
    finally:
        copy.pop_pass()


def _find_followup_threat(
    copy: cshogi.Board, own_color: int, opp_color: int, sq: int, piece_type: int
) -> Optional[dict]:
    matched: set[str] = set()
    example_move: Optional[int] = None
    for followup in copy.legal_moves:
        if cshogi.move_from(followup) != sq:
            continue
        copy.push(followup)
        try:
            patterns = _classify_followup(copy, own_color, opp_color, followup)
        finally:
            copy.pop()
        if patterns:
            matched.update(patterns)
            if example_move is None:
                example_move = followup
    if not matched:
        return None
    return {
        "square": square_name(sq),
        "piece": PIECE_NAMES[piece_type],
        "patterns": sorted(matched),
        "example_move_usi": cshogi.move_to_usi(example_move),
    }


def _classify_followup(copy: cshogi.Board, own_color: int, opp_color: int, followup: int) -> list[str]:
    """成り込んだ駒の追撃手1つを§17.1のパターンA〜Dに照らして判定する。"""
    dest = cshogi.move_to(followup)
    pieces_now = copy.pieces
    gives_check = copy.is_check()
    dest_safe = not attackers(pieces_now, own_color, dest)

    hanging_count = 0
    for tsq, code in enumerate(pieces_now):
        if code == 0 or (code >= _WHITE_OFFSET) != (own_color == cshogi.WHITE):
            continue
        if code % _WHITE_OFFSET == cshogi.KING:
            continue
        if dest not in attackers(pieces_now, opp_color, tsq):
            continue  # 今動いた駒自身の利きでなければ対象外
        if attackers(pieces_now, own_color, tsq):
            continue  # 紐が付いていれば対象外
        hanging_count += 1

    patterns = []
    if gives_check and hanging_count:
        patterns.append("A")
    if gives_check and dest_safe:
        patterns.append("B")
    if not gives_check and hanging_count >= 2:
        patterns.append("C")
    if not gives_check and hanging_count and dest_safe:
        patterns.append("D")
    return patterns


# --- 大駒の捕獲判定・トラップ検出(§18) ---------------------------------------


def trapped_major_pieces(board: cshogi.Board) -> list[dict]:
    """相手の飛・角(成りを含む: 龍・馬)のうち、盤上の合法な移動先の全てに
    手番側の利きが及んでいて安全に逃げられない駒の一覧(§18.1)。boardは
    手番側(攻撃側)の局面。盤面は変更しない。

    既存のmajor_piece_drop_threatsと同じくpush_passで「相手が実際に指せる
    合法手」を仮定して評価する。打ち込み(持ち駒からの新規配置)は対象外
    (§17のmajor_piece_drop_threatsの範疇)で、盤上に既にある大駒の移動可能性
    のみを判定する。静的な利き数のみで判定するため、ピンや複数回の取り合いの
    最終損得は考慮しない(§13.3の限界を踏襲する既知の制約)。
    """
    if board.is_check():
        return []

    own_color = board.turn
    opp_color = cshogi.WHITE if own_color == cshogi.BLACK else cshogi.BLACK
    copy = _copy_board(board)
    pieces = copy.pieces
    opp_is_white = opp_color == cshogi.WHITE
    targets = [
        sq for sq, code in enumerate(pieces)
        if code and (code >= _WHITE_OFFSET) == opp_is_white
        and (code % _WHITE_OFFSET) in _MAJOR_PIECE_TYPES
    ]
    if not targets:
        return []

    results = []
    copy.push_pass()
    try:
        for sq in targets:
            moves = [m for m in copy.legal_moves if cshogi.move_from(m) == sq]
            if any(_escapes_safely(copy, own_color, m) for m in moves):
                continue
            piece_type = pieces[sq] % _WHITE_OFFSET
            results.append({
                "square": square_name(sq),
                "piece": PIECE_NAMES[piece_type],
                "legal_move_count": len(moves),
            })
    finally:
        copy.pop_pass()
    return results


def _escapes_safely(copy: cshogi.Board, own_color: int, move: int) -> bool:
    """moveを実際に指した後、その移動先に手番側の利きが無ければ安全な退避。"""
    dest = cshogi.move_to(move)
    copy.push(move)
    try:
        return not attackers(copy.pieces, own_color, dest)
    finally:
        copy.pop()


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
