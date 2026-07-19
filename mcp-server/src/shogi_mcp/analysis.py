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


_SHELTER_PIECE_TYPES = frozenset({
    cshogi.GOLD, cshogi.SILVER,
    cshogi.PROM_PAWN, cshogi.PROM_LANCE, cshogi.PROM_KNIGHT, cshogi.PROM_SILVER,
})


def _king_shelter_count(pieces: list[int], color: int, king_sq: int) -> int:
    """colorの玉(king_sq)に隣接するcolor自身の金・銀(金と同格の成駒を含む)の数(§22.1)。

    _KING_ZONES(§13.5で玉の安全度項のために前計算済み)をそのまま流用する。
    """
    is_white = color == cshogi.WHITE
    count = 0
    for zone_sq in _KING_ZONES[king_sq]:
        code = pieces[zone_sq]
        if code == 0 or (code >= _WHITE_OFFSET) != is_white:
            continue
        if code % _WHITE_OFFSET in _SHELTER_PIECE_TYPES:
            count += 1
    return count


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


def _fork_targets(pieces_now: list[int], attacker_color: int, defender_color: int, dest: int) -> list[dict]:
    """destに今動いた駒(attacker_color)自身の利きが新たに当たっている、かつ玉以外の
    紐(defender_color自身の利き)が付いていないdefender_colorの駒(玉を除く)一覧。
    §17.1の_classify_followupと同じ「動かした駒自身の利き」判定をdest基準で行う。

    紐が玉のみ(king_only_defense、§19.1と同じ考え方)の場合は「実質的に紐なし」
    として対象に含める(§27.1)。玉による防御は取り返すと玉自身が危険な位置に
    出る特殊なケースであり、他の駒による紐と同列に安全とは見なせないため。
    games/2026-07-17_170612.kif 50手目△７八銀打(6七金・8七金の両取り、
    6七金の唯一の紐が自玉)が実例。
    """
    defender_is_white = defender_color == cshogi.WHITE
    targets = []
    for tsq, code in enumerate(pieces_now):
        if code == 0 or (code >= _WHITE_OFFSET) != defender_is_white:
            continue
        piece_type = code % _WHITE_OFFSET
        if piece_type == cshogi.KING:
            continue
        if dest not in attackers(pieces_now, attacker_color, tsq):
            continue  # 今動いた駒自身の利きでなければ対象外
        defenders = attackers(pieces_now, defender_color, tsq)
        has_real_defender = any(pieces_now[d] % _WHITE_OFFSET != cshogi.KING for d in defenders)
        if has_real_defender:
            continue  # 玉以外の紐が付いていれば対象外
        targets.append({"square": square_name(tsq), "piece": PIECE_NAMES[piece_type]})
    return targets


_FORK_DROP_ONLY_PIECES = (cshogi.SILVER, cshogi.GOLD, cshogi.KNIGHT, cshogi.LANCE)


def major_piece_fork_opportunities(
    board: cshogi.Board, color: Optional[int] = None, include_checks: bool = False
) -> list[dict]:
    """colorの持ち駒にある飛・角の打ち込み、盤上の未成りの飛・角の移動、または
    colorの持ち駒にある銀・金・桂・香の打ち込みが、両取りになる機会の一覧
    (§24.1、include_checksは§25.1、銀・金・桂・香の打ち込みは§27.1)。
    boardは攻撃側の局面。盤面は変更しない。

    colorは攻撃側(省略時はboard.turn)。成りを伴う手は対象外(成り込みを伴う
    打ち込みはmajor_piece_drop_threatsの範疇であり、本関数はそれと重複しない
    両取りのみを対象とする)。

    銀・金・桂・香は**持ち駒からの打ち込みのみ**を対象とし、盤上の移動は
    対象外(§27.1)。飛・角と異なり長い走り利きを持たず、盤上の移動まで
    含めると既存のmajor_piece_drop_threats/own_attacked_afterと役割が
    重複するため、意図的にスコープを打ち込みのみに絞っている。

    include_checks(既定False)がFalseのとき、王手を伴う手も対象外(王手を伴う
    両取りはallows_mate/check_evasionsの範疇として除外する、§24.1)。Trueのとき
    その除外のみを外し、王手と同時に成立する両取りも対象に含める(§25.1: `allows_mate`
    は強制詰みのみを検出するため、「詰みには至らないが王手と両取りが同時に成立し
    駒得される」パターンを拾うために使う)。王手を伴う場合、玉への当たり(王手
    そのもの)を1駒分の当たりとして数え、_fork_targets(玉を除く)が返す玉以外の
    当たり駒が1つ以上あれば「王手+もう1駒への当たり」を両取りとして採用する
    (玉以外2駒以上を要求する非王手時とは必要数が異なる。実戦で確認された
    「王手をかけながら別の駒にも当たる」パターンを漏れなく拾うための調整、
    games/2026-07-17_074805.kif 32手目△６六角打が該当する実例)。

    判定は_classify_followup(§17.1)と同じ「動かした駒自身の利きが新たに
    当たっている、かつ紐(自分の利き)が付いていない相手の駒(玉を除く)」の
    集計(_fork_targets)を行う。既知の限界: 動かした駒自身の利き以外による
    当たりは対象外、紐が1つでもあればその駒は対象から外れる(ピン・取り合いの
    最終損得は考慮しない)。王手中は空リスト。
    """
    if board.is_check():
        return []

    copy = _copy_board(board)
    own_color = color if color is not None else copy.turn
    opp_color = cshogi.WHITE if own_color == cshogi.BLACK else cshogi.BLACK
    needs_pass = copy.turn != own_color
    if needs_pass:
        copy.push_pass()
    try:
        candidates = [
            m for m in copy.legal_moves
            if not cshogi.move_is_promotion(m)
            and (
                cshogi.hand_piece_to_piece_type(cshogi.move_drop_hand_piece(m))
                in (cshogi.ROOK, cshogi.BISHOP) + _FORK_DROP_ONLY_PIECES
                if cshogi.move_is_drop(m)
                else cshogi.move_from_piece_type(m) in (cshogi.ROOK, cshogi.BISHOP)
            )
        ]
        results = []
        for m in candidates:
            copy.push(m)
            try:
                gives_check = copy.is_check()
                if gives_check and not include_checks:
                    continue
                targets = _fork_targets(copy.pieces, own_color, opp_color, cshogi.move_to(m))
            finally:
                copy.pop()
            min_targets = 1 if gives_check else 2
            if len(targets) < min_targets:
                continue
            is_drop = cshogi.move_is_drop(m)
            piece_type = (
                cshogi.hand_piece_to_piece_type(cshogi.move_drop_hand_piece(m))
                if is_drop
                else cshogi.move_from_piece_type(m)
            )
            results.append({
                "square": square_name(cshogi.move_to(m)),
                "piece": PIECE_NAMES[piece_type],
                "source": "drop" if is_drop else "board",
                "targets": targets,
                "example_move_usi": cshogi.move_to_usi(m),
            })
        return results
    finally:
        if needs_pass:
            copy.pop_pass()


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

    own_color = copy.turn
    opp_hand = hand_white if own_color == cshogi.BLACK else hand_black
    own_attacked_squares = major_piece_attacked_squares(copy, color=own_color)
    king_zone_names = {square_name(z) for z in _KING_ZONES[copy.king_square(own_color)]}
    mating_net_risk = any(e["square"] in king_zone_names for e in own_attacked_squares)
    king_safety = {
        "own_shelter_count": _king_shelter_count(copy.pieces, own_color, copy.king_square(own_color)),
        "opponent_hand_value": sum(n * v for n, v in zip(opp_hand, HAND_PIECE_VALUES)),
        "mating_net_risk": mating_net_risk,
    }

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
        "major_piece_fork_opportunities": major_piece_fork_opportunities(copy),
        "major_piece_attacked_squares": own_attacked_squares,
        "king_safety": king_safety,
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
    major_piece_drop_threats_after/trapped_major_pieces_after(§20.2)は、
    この手をpushした直後(応手を読む前)の局面に対するmajor_piece_drop_threats/
    trapped_major_pieces(mover_color視点、攻撃側=自分)。own_attacked_afterと
    同様、is_mateの候補には付けない。major_piece_drop_threats_afterの各
    エントリのsource(§21.1)は、相手の持ち駒からの打ち込みなら"drop"、
    盤上の未成りの飛・角の前進なら"board"。
    own_trapped_major_pieces_after(§21.2)は、trapped_major_piecesを攻守
    逆転(攻撃側=相手、防御側=自分)で呼んだ結果。空でなければ、この手を
    指した直後に自分の飛・角(成りを含む)が捕獲確定(トラップ)になって
    いることを示す。is_mateの候補には付けない。
    own_king_shelter_after(§22.2)は、自玉に隣接する自分の金・銀(金と
    同格の成駒を含む)の数を、immediately_after(着手直後)/after_pv(読み筋
    reply_pv_usiを最後まで適用した後)の2値で返す。after_pvは
    search_depth_completed == 0(信頼できる読みなし)の場合null
    (material_changeがnullになる場合と同じ扱い)。is_mateの候補には付けない。
    mate_ply(§22.3)は着手直後の局面でallows_mateを判定する詰み探索の深さ。
    既定はDEFAULT_MATE_PLY(5)。
    own_attacked_after_pv(§24.2)は、読み筋(reply_pv_usi)を最後まで適用した
    局面に対するattacked_pieces(mover_color視点)の上位5件。own_attacked_after
    (着手直後、応手を読む前)には現れない、読み筋の途中で自分の駒に新たに
    生じる当たりを検出できる。search_depth_completed == 0の場合はnull
    (material_changeがnullになる場合と同じ扱い)。is_mateの候補には付けない。
    own_trapped_major_pieces_after_pv(§28.1)は、読み筋(reply_pv_usi)を
    最後まで適用した局面に対するtrapped_major_pieces(own_trapped_major_
    pieces_afterと同じ攻守の向き: 攻撃側=相手、防御側=自分)。空でなければ、
    読み筋の最後で自分の飛・角(成りを含む)が捕獲確定(トラップ)になって
    いることを示す(合駒の後に玉が接近して退路を失う、等)。
    own_trapped_major_pieces_after(着手直後、応手を読む前)には現れない、
    読み筋の途中で生じるトラップを検出できる。trapped_major_piecesの
    color引数によるpush_passの自動切り替え(§20.1)により、読み筋の総手数の
    偶奇(PV終端の手番)に関わらず呼び出せる(mate_threat_after_pvのような
    手番パリティの分岐は不要)。既知の限界: trapped_major_piecesは
    board.is_check()の局面では空リストを返す設計(§18.1)のため、PV終端が
    王手のまま途切れている場合はトラップを見逃すことがある
    (own_trapped_major_pieces_after/trapped_major_pieces_afterと同じ制約)。
    reply_pv_usiが材料点+玉の安全度ベースの浅い探索の結果であり実際の相手の
    指し手と一致するとは限らない点もmaterial_changeと同じ制約。
    search_depth_completed == 0の場合はnull。is_mateの候補には付けない。
    mate_threat_after_pv(§24.3)は、読み筋を最後まで適用した局面に対する
    find_mate_threat(mate_ply)の結果({found, within_ply, first_move_usi}、
    詰めろなしはnull)。「読み筋の最後で自分が何もしなければ、相手から
    詰みがあるか」の早期警告。reply_pv_usiは材料点+玉の安全度ベースの浅い
    探索の結果であり、実際の相手の指し手と一致するとは限らない
    (material_changeと同じ制約)。search_depth_completed == 0の場合はnull。
    is_mateの候補には付けない。
    既知の限界: 読み筋の総手数の偶奇によっては、読み筋終端の手番がこの手を
    指した側に戻っていない(相手の手番のまま)ことがある(反復深化の打ち切り・
    静止探索での追加の取り合いにより発生しうる、実戦局面で確認済み)。
    その場合はfind_mate_threatを呼ぶと逆方向の判定になってしまうため、
    mate_threat_after_pvはnullを返す(見逃しうる、隠さず文書化する)。
    opponent_fork_threats_after(§25.1)は、この手をpushした直後(応手を読む前、
    major_piece_drop_threats_afterと同じ時点)の局面に対する
    major_piece_fork_opportunities(相手視点、include_checks=True)。非空なら、
    この手を指した直後に相手の飛・角が王手を伴う両取りを成立させられることを
    示す(§24.1のmajor_piece_fork_opportunitiesは既定で王手を伴う手を除外して
    いるが、ここではその除外を外すことで「詰みには至らないが王手と両取りが
    同時に成立する」パターンも拾う)。既知の限界は§24.1と同じ(動かした駒
    自身の利き以外による当たりは対象外、紐が1つでもあれば対象から外れる)。
    is_mateの候補には付けない。
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
        mover_king_sq = copy.king_square(mover_color)  # 着手直後(候補手自体で玉が動いた場合も反映済み)
        entry["own_king_shelter_after"] = {
            "immediately_after": _king_shelter_count(copy.pieces, mover_color, mover_king_sq),
            "after_pv": None,
        }
        entry["major_piece_drop_threats_after"] = major_piece_drop_threats(copy, color=mover_color)
        entry["trapped_major_pieces_after"] = trapped_major_pieces(copy, color=mover_color)
        entry["own_trapped_major_pieces_after"] = trapped_major_pieces(copy, color=opponent_color)
        # §25.1: この手を指した直後、相手の飛・角が王手両取りを成立させられるか。
        # copy.turnは既にopponent_color(候補手をpush直後)なのでpush_passは不要。
        entry["opponent_fork_threats_after"] = major_piece_fork_opportunities(
            copy, color=opponent_color, include_checks=True
        )

        searcher = _Searcher(copy, node_limit)
        score, pv, completed_depth = _iterative_deepen(searcher, depth)
        entry["search_depth_completed"] = completed_depth
        entry["search_truncated"] = searcher.truncated
        if completed_depth == 0:
            entry["material_change"] = None
            entry["reply_pv_usi"] = []
            # pvが空(読み筋が信頼できない)なので候補手自体の捕り駒のみで判定する(§16.1)。
            entry["major_piece_trade"] = _captures_major_piece([move])
            entry["own_attacked_after_pv"] = None
            entry["mate_threat_after_pv"] = None
            entry["own_trapped_major_pieces_after_pv"] = None
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
            entry["own_king_shelter_after"]["after_pv"] = _king_shelter_count(
                copy.pieces, mover_color, copy.king_square(mover_color)
            )
            # §24.2: 読み筋終端(手番はこの手を指した側=mover_colorに戻っている)の自駒への当たり。
            entry["own_attacked_after_pv"] = attacked_pieces(copy, color=mover_color)[:5]
            # §28.1: 読み筋終端で自分の飛・角(own_trapped_major_pieces_afterと同じ攻守の向き)が
            # 捕獲確定(トラップ)になっていないか。trapped_major_piecesのcolor引数による
            # push_passの自動切り替え(§20.1)により、読み筋の総手数の偶奇(PV終端の手番)に
            # 関わらず呼び出せる。
            entry["own_trapped_major_pieces_after_pv"] = trapped_major_pieces(copy, color=opponent_color)
            # §24.3: 読み筋終端で、この手を指した側が何もしなければ相手から詰みがあるか。
            # find_mate_threatはboard.turn側が「何もしなければ」を仮定するため、
            # 読み筋終端でcopy.turn == mover_colorのとき(読み筋の総手数が奇数、
            # 手番がこの手を指した側に戻っている)のみ意味のある判定になる。
            # 読み筋の総手数が偶数(反復深化の打ち切りや静止探索での追加の
            # 取り合いにより発生しうる、実戦局面で確認済み)だとcopy.turnは
            # 相手側のままで、その場合にfind_mate_threatを呼ぶと逆方向
            # (相手が何もしなければこの手を指した側が詰ませられるか)を
            # 判定してしまうため、その場合はnullとする(既知の限界)。
            if copy.turn == mover_color:
                threat_after_pv = find_mate_threat(copy, mate_ply)
            else:
                threat_after_pv = None
            if threat_after_pv is not None:
                threat_move, threat_ply_found = threat_after_pv
                entry["mate_threat_after_pv"] = {
                    "found": True,
                    "within_ply": threat_ply_found,
                    "first_move_usi": cshogi.move_to_usi(threat_move),
                }
            else:
                entry["mate_threat_after_pv"] = None
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


def major_piece_drop_threats(board: cshogi.Board, color: Optional[int] = None) -> list[dict]:
    """自陣後方への安全な大駒打ち込み、または盤上の未成り大駒の前進が、
    成り込みと組み合わさって王手・両取り・安全な当たりに発展する脅威の
    一覧(§17.1、盤上前進版は§21.1)。boardは防御側の局面。盤面は変更しない。

    「防御側が2手連続で何もしなかった」場合の脅威を、既存のfind_mate_threat
    (§11.2)と同じくpush_passで仮定して検出する。王手中(push_passが使えない)と、
    打ち込み自体が直接王手になる候補はこの関数の対象外(既存の王手検出・
    回避検証の範疇)。

    colorを省略すると従来どおり手番側(board.turn)が防御側。colorを指定した
    場合、board.turn == colorのとき(analyze_position等、従来どおりの呼び出し)
    のみ最初のpush_passを行う。board.turn != colorのとき(verify_movesが候補手を
    push直後、既に相手の実手番)は、その最初のpush_passを省略する(§20.1)。

    各エントリの`source`は脅威の出所を示す。`"drop"`は相手の持ち駒からの
    打ち込み(`square`は打ち込み先の空きマス)、`"board"`は盤上に既にある
    未成りの飛・角の前進(`square`はその駒の現在地)。実際の脅威手(移動元・
    移動先・成りの有無)は出所によらず`example_move_usi`で一意に分かる。
    既に成っている駒(龍・馬)は`"board"`の対象外(§21.1)。
    """
    if board.is_check():
        return []

    copy = _copy_board(board)
    own_color = color if color is not None else copy.turn
    opp_color = cshogi.WHITE if own_color == cshogi.BLACK else cshogi.BLACK
    needs_initial_pass = copy.turn == own_color

    results = []
    hand_black, hand_white = copy.pieces_in_hand
    opp_hand = hand_black if opp_color == cshogi.BLACK else hand_white
    drop_piece_types = []
    if opp_hand[6] > 0:  # 飛
        drop_piece_types.append(cshogi.ROOK)
    if opp_hand[5] > 0:  # 角
        drop_piece_types.append(cshogi.BISHOP)
    if drop_piece_types:
        pieces = copy.pieces
        back_ranks = (6, 7, 8) if own_color == cshogi.BLACK else (0, 1, 2)
        candidate_squares = [
            sq for sq in range(81)
            if pieces[sq] == 0 and sq % 9 in back_ranks and not attackers(pieces, own_color, sq)
        ]
        for sq in candidate_squares:
            for piece_type in drop_piece_types:
                entry = _check_drop_threat(copy, own_color, opp_color, sq, piece_type, needs_initial_pass)
                if entry is not None:
                    entry["source"] = "drop"
                    results.append(entry)

    results.extend(_board_advance_threats(copy, own_color, opp_color, needs_initial_pass))
    return results


def _board_advance_threats(
    copy: cshogi.Board, own_color: int, opp_color: int, needs_initial_pass: bool
) -> list[dict]:
    """盤上に既にある相手の未成りの飛・角が、次の一手で自陣3段目以内へ
    移動かつ成ることで§17.1のパターンA〜Dを実現できるかを判定する(§21.1)。
    _find_followup_threat/_classify_followupの判定ロジックを、「打ち込み直後」
    ではなく「盤上の駒がそのまま前進」する場合に適用する。既に成っている駒
    (龍・馬)は「成り込み」の前提に該当しないため対象外。
    """
    pieces = copy.pieces
    opp_is_white = opp_color == cshogi.WHITE
    back_ranks = (6, 7, 8) if own_color == cshogi.BLACK else (0, 1, 2)
    targets = [
        sq for sq, code in enumerate(pieces)
        if code and (code >= _WHITE_OFFSET) == opp_is_white
        and (code % _WHITE_OFFSET) in (cshogi.ROOK, cshogi.BISHOP)  # 未成りのみ
    ]
    if not targets:
        return []

    if needs_initial_pass:
        copy.push_pass()
    try:
        results = []
        for sq in targets:
            matched: set[str] = set()
            example_move: Optional[int] = None
            for m in copy.legal_moves:
                if cshogi.move_from(m) != sq:
                    continue
                if not cshogi.move_is_promotion(m):
                    continue
                if cshogi.move_to(m) % 9 not in back_ranks:
                    continue
                copy.push(m)
                try:
                    patterns = _classify_followup(copy, own_color, opp_color, m)
                finally:
                    copy.pop()
                if patterns:
                    matched.update(patterns)
                    if example_move is None:
                        example_move = m
            if matched:
                piece_type = pieces[sq] % _WHITE_OFFSET
                results.append({
                    "square": square_name(sq),
                    "piece": PIECE_NAMES[piece_type],
                    "source": "board",
                    "patterns": sorted(matched),
                    "example_move_usi": cshogi.move_to_usi(example_move),
                })
        return results
    finally:
        if needs_initial_pass:
            copy.pop_pass()


def _check_drop_threat(
    copy: cshogi.Board, own_color: int, opp_color: int, sq: int, piece_type: int,
    needs_initial_pass: bool = True,
) -> Optional[dict]:
    """1つの打ち込み候補(マス・駒種)を検証する。呼び出し後、copyは元の局面に復元される。

    needs_initial_pass=False(§20.1)のときは、copy.turnが既にopp_color(相手の
    実手番)であることを前提に最初のpush_pass/pop_passを省略する。打ち込み後の
    追撃を読むための2回目のpush_passは常に行う(own_color側が「何もしなかった」
    ことを仮定する必要があるため)。
    """
    usi = f"{_DROP_PIECE_TYPES[piece_type]}*{_usi_square(sq)}"
    if needs_initial_pass:
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
        if needs_initial_pass:
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


def trapped_major_pieces(board: cshogi.Board, color: Optional[int] = None) -> list[dict]:
    """相手の飛・角(成りを含む: 龍・馬)のうち、盤上の合法な移動先の全てに
    攻撃側の利きが及んでいて安全に逃げられない駒の一覧(§18.1)。boardは
    攻撃側の局面。盤面は変更しない。

    既存のmajor_piece_drop_threatsと同じくpush_passで「相手が実際に指せる
    合法手」を仮定して評価する。打ち込み(持ち駒からの新規配置)は対象外
    (§17のmajor_piece_drop_threatsの範疇)で、盤上に既にある大駒の移動可能性
    のみを判定する。静的な利き数のみで判定するため、ピンや複数回の取り合いの
    最終損得は考慮しない(§13.3の限界を踏襲する既知の制約)。

    各エントリの`attackers`は、その駒へ現在実際に利いている攻撃側(own_color)の
    駒数(§20.3)。0は「退避不可だがまだ当たっていない」、1以上は「既に当たって
    おり次の一手で無償捕獲できる可能性が高い」ことを示す。

    colorを省略すると従来どおり手番側(board.turn)が攻撃側。colorを指定した
    場合、board.turn == colorのときのみpush_passを行い、board.turn != colorの
    とき(verify_movesが候補手をpush直後)は省略する(§20.1)。
    """
    if board.is_check():
        return []

    own_color = color if color is not None else board.turn
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
    needs_initial_pass = copy.turn == own_color
    if needs_initial_pass:
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
                "attackers": len(attackers(pieces, own_color, sq)),
            })
    finally:
        if needs_initial_pass:
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


def major_piece_attacked_squares(board: cshogi.Board, color: Optional[int] = None) -> list[dict]:
    """colorから見て、相手の飛・角(成りを含む: 龍・馬)が現在利いている升目の
    一覧(§25.3)。boardは防御側の局面。盤面は変更しない。

    colorは防御側(省略時はboard.turn、major_piece_drop_threatsと同じ既定の
    向き)。攻撃側はcolorの反対側。対象は攻撃側の盤上にある未成り・成り済みを
    問わない飛・角(龍・馬を含む点が§21.1/§24.1と異なる。利き筋の可視化その
    ものが目的であり、成り込み判定ではないため対象を絞る理由がない)。

    走り利きのみを対象とする(龍・馬の隣接8方向への追加の1マス利きは対象外)。
    既存の_RAY_PATHS(§13.2)を対象駒自身の升目を起点に流用し、飛・龍は縦横
    4方向、角・馬は斜め4方向の経路のみを使って、盤端または最初の駒(遮蔽物、
    自分の駒でも相手の駒でも利きはそこで止まる)までの全マスを「利きが
    通っている」対象として収集する(遮蔽物の升目自体は含み、その先は含まない)。
    同じ升目が複数の大駒から利いている場合は複数エントリになる。

    既知の限界: 静的な利き筋の可視化のみであり、ピン・その升目に自分の駒を
    置いた場合の取り合いの最終損得までは判定しない(候補手自体の安全性は
    引き続きverify_movesのdestination/own_attacked_afterで確認する必要が
    ある)。push_passを使わない静的な走査のため、王手中でも通常どおり計算する
    (king_safety(§22.4)と同じ理由)。
    """
    pieces = board.pieces
    defender_color = color if color is not None else board.turn
    attacker_color = cshogi.WHITE if defender_color == cshogi.BLACK else cshogi.BLACK
    attacker_is_white = attacker_color == cshogi.WHITE

    results = []
    for psq, code in enumerate(pieces):
        if code == 0 or (code >= _WHITE_OFFSET) != attacker_is_white:
            continue
        piece_type = code % _WHITE_OFFSET
        if piece_type not in _MAJOR_PIECE_TYPES:
            continue
        attacker_square = square_name(psq)
        piece_name = PIECE_NAMES[piece_type]
        for path, vec in _RAY_PATHS[psq]:
            if vec not in _RAY_SETS[code]:
                continue
            for tsq in path:
                results.append({
                    "square": square_name(tsq),
                    "piece": piece_name,
                    "attacker_square": attacker_square,
                })
                if pieces[tsq] != 0:
                    break
    return results


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
