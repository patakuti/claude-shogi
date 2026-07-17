import random

import cshogi

from shogi_mcp import analysis


def _sq(file: int, rank: int) -> int:
    """筋・段(1-9)からマス番号へ。"""
    return (file - 1) * 9 + (rank - 1)

# 頭金の1手詰め: 後手玉5a、先手歩5c(5bに利き)、先手持ち駒 金。▲G*5bで詰み。
MATE_IN_1_SFEN = "4k4/9/4P4/9/9/9/9/9/4K4 b G 1"

# 3手詰め: 後手玉5b、先手歩5d、先手持ち駒 金2。▲G*5c 玉(どこへ逃げても) ▲金打 まで。
# (初手G*5cは歩に支えられた王手だが、玉が一段目に逃げられるため1手詰めではない)
MATE_IN_3_SFEN = "9/4k4/9/4P4/9/9/9/9/4K4 b 2G 1"

# 詰めろ: 上の3手詰めを先後反転した形。先手番だがパスすると後手から詰まされる。
TSUMERO_SFEN = "4k4/9/9/9/9/9/9/6+b2/8K b g 1"

# 王手中(後手飛車が5gから先手玉5iを直射): push_passが使えないため詰めろ検出はスキップされる。
IN_CHECK_SFEN = "4k4/9/9/9/9/9/4r4/9/4K4 b - 1"

# タダ捨てチェック用: 先手飛5e。5dの後手歩は5cの後手金に守られており、
# ▲5五飛→5四(歩を取る)は金で取り返されて大損。
BLUNDER_SFEN = "4k4/9/4g4/4p4/4R4/9/9/9/4K4 b - 1"

# 浮き駒チェック用: 後手金5cがどこからも守られておらず、▲飛5三+でタダ取りできる。
FREE_GOLD_SFEN = "4k4/9/4g4/9/4R4/9/9/9/4K4 b - 1"

# 両取りチェック用: ▲桂6五(6g5e)が後手飛6cと後手金4cの両取りになる。
# 先手玉は金で守り、後手飛車が王手で反撃しながら桂を回収する筋を消してある。
# 後手の最善は飛5cと逃げて金に紐を付ける受けで、それでも桂金交換で先手の駒得になる。
FORK_SFEN = "4k4/9/3r1g3/9/9/9/3N5/6GK1/9 b - 1"

# 頓死チェック用: 後手歩5gが5hに利いており、後手が金を持っているため
# 放置すると△G*5hの1手詰め。▲G*5hと受ければ詰みはない。
SUDDEN_DEATH_SFEN = "4k4/9/9/9/9/9/4p4/9/4K4 b Gg 1"

# 当たり一覧用: 先手銀5e(後手歩5dの当たり・紐なし)、先手歩1e(後手香1dの当たり・紐なし)。
HANGING_SFEN = "4k4/9/9/4p3l/4S3P/9/9/9/4K4 b - 1"

# 紐付き: 上の銀5eに金5fで紐を付けた形(歩1eと香1dは除去)。
DEFENDED_SFEN = "4k4/9/9/4p4/4S4/4G4/9/9/4K4 b - 1"

# 受けなしの王手: 3手詰め(MATE_IN_3)の初手▲G*5cを指した直後の局面(後手番)。
# 後手玉はどこへ逃げても持ち駒の金で1手詰め。
NO_ESCAPE_CHECK_SFEN = "9/4k4/4G4/4P4/9/9/9/9/4K4 w G 1"

# 玉の危険度比較用: 材料は同じ(後手飛1枚)で、飛車が先手玉のコビン(4筋)を
# 直射している形と、玉から離れた1筋にいる形。
KING_EXPOSED_SFEN = "4k4/9/9/9/3r5/9/9/9/4K4 b - 1"
KING_SAFE_SFEN = "4k4/9/9/9/8r/9/9/9/4K4 b - 1"

# destination(§14.3)検証用: 実対局の再現(馬の利きにある3四への桂打ち)。
# 後手馬6七が3四(3d)を直射しており、3四に先手の紐はない。持ち駒は先手桂1枚。
UNDEFENDED_DROP_SFEN = "4k4/9/9/9/9/9/3+b5/9/4K4 b N 1"

# 上と同型だが、先手金3三が3四に紐を付けている(own_supports==1になること)。
DEFENDED_DROP_SFEN = "4k4/9/6G2/9/9/9/3+b5/9/4K4 b N 1"

# king_only_defense(§19.4(e))検証用: 上と同型だが、玉が4四にいて3四に紐を
# 付けている(玉のみが紐であること)。
KING_ONLY_DEFENSE_DROP_SFEN = "4k4/9/9/5K3/9/9/3+b5/9/9 b N 1"

# own_king_shelter_after(§22.2)検証用 ----------------------------------------

# games/2026-07-15_182533.kif 35手目相当(34手目△6五銀の直後)の再現局面。
# ▲5五歩(5f5e)は着手直後は玉の守備駒に変化がないが、読み筋を最後まで適用すると
# 玉隣接の金(6八)が最前線へ釣り出され、隣接金銀の数が1→0に減る(振り返りで判明)。
KING_SHELTER_PV_DECREASE_SFEN = (
    "l4gknl/3rg1sb1/p3pp1pp/1pp3p2/1n1s3P1/1SPSP1P2/PP1G1P2P/1BK1G2R1/LN5NL b Pp 35"
)

# 候補手が玉の移動そのものである場合(§22.6(e))の再現局面。games/2026-07-15_182533.kif
# 67手目相当(66手目△7八金打による王手直後)。候補8h9iは黒玉自身を9九へ動かす手。
KING_MOVES_ITSELF_SFEN = (
    "+R4gknl/4g1s2/p3pp1pp/1pp3p2/1n1pS2P1/1SP3P2/PP1gbP2P/1Kg3R2/1N5NL b BSLPlp 67"
)

# major_piece_trade(§16.1)検証用 -------------------------------------------

# 大駒・小駒を含まない静かな手: 候補も読み筋も大駒に一切触れない。
QUIET_NO_MAJOR_PIECE_SFEN = "4k4/9/9/9/4P4/9/9/9/4K4 b - 1"

# 候補手自体が後手飛を直取り(5五飛→5三)。
CAPTURE_ROOK_SFEN = "4k4/9/4r4/9/4R4/9/9/9/4K4 b - 1"

# 候補手自体は捕らないが(9七歩→9六歩の静かな手)、直後の後手番で
# 後手飛1三が無防備な先手飛1五を1三→1五で直取りできる(読み筋側で検出)。
PV_CAPTURES_OWN_ROOK_SFEN = "4k4/9/8r/9/8R/9/P8/9/4K4 b - 1"

# 候補手自体が後手の龍(成駒)を直取り(5五飛→5三)。
CAPTURE_DRAGON_SFEN = "4k4/9/4+r4/9/4R4/9/9/9/4K4 b - 1"

# major_piece_fork_opportunities(§24.1)検証用 -------------------------------

# 両取り成立: 先手持ち駒の角を4四・5五・6六のいずれに打っても、同一の斜線上に
# ある後手飛3三と後手金7七の両方に当たり、いずれにも紐がない。
FORK_OPPORTUNITY_DROP_SFEN = "1k7/9/6r2/9/9/9/2g6/9/4K4 b B 1"

# 当たる駒が1つのみ(後手飛3三のみ、後手金なし): 両取りにならない。
FORK_OPPORTUNITY_SINGLE_TARGET_SFEN = "1k7/9/6r2/9/9/9/9/9/4K4 b B 1"

# 両方に紐が付いている(後手飛3三は後手金4二、後手金7七は後手金7八に守られる): 両取り対象外。
FORK_OPPORTUNITY_BOTH_DEFENDED_SFEN = "1k7/5g3/6r2/9/9/9/2g6/2g6/4K4 b B 1"

# 盤上の角(9九、不成)が2二へ移動して後手飛1三・後手金3一の両取りが成立する形。
# 2二は先手の成り込みゾーン(1-3段目)内だが、成る手は対象外で不成のみ検出されること。
FORK_OPPORTUNITY_BOARD_MOVE_SFEN = "k5g2/9/8r/9/9/9/9/9/B3K4 b - 1"

# 上と同型だが白玉を1一に置き、同じ手(9九2二)が王手を伴うようにした形: 対象外。
FORK_OPPORTUNITY_GIVES_CHECK_SFEN = "6g1k/9/8r/9/9/9/9/9/B3K4 b - 1"

# games/2026-07-16_074057.kif 36手目相当(白の8b8fの直後、黒の37手目の直前)の
# 実戦再現。B*9eが後手桂7三・後手飛8六の両取りになる(振り返りで判明した見落とし)。
FORK_OPPORTUNITY_REAL_GAME_SFEN = (
    "l4gsnl/4g1k2/p1n1pp1p1/2p1s1p2/3P4p/1rP1SPP2/P1N1PG1PP/3R2SK1/L4G1NL b B2Pbp 37"
)


# verify_movesのown_attacked_after_pv/mate_threat_after_pv(§24.2, §24.3)検証用 --

# own_attacked_after_pv: 候補1七1六(1g1f)自体は無関係な静かな手。着手直後は
# 先手飛5五が白角9一ににらまれている(既にhanging)のみだが、読み筋(白角が
# 9一から5五へ飛を取りに来る、深さ1で一意に選ばれる)適用後は角が5五からの
# 斜線で先手桂7七に新たに当たる(着手直後には無かった当たり)。
OWN_ATTACKED_AFTER_PV_SFEN = "b7k/9/9/9/4R4/9/2N5P/9/4K4 b - 1"

# mate_threat_after_pv: 候補9七9六(9g9f)自体は無関係な静かな手。読み筋
# (白馬が1六から3八の先手歩を取りつつ、単騎で受けなしの詰めろを組む形に
# 移動する。深さ1で一意に選ばれる)適用前は詰めろが存在しないが、適用後は
# 先手が何もしなければ後手の持ち駒金で1手詰め(G*2八)になる。
MATE_THREAT_AFTER_PV_SFEN = "4k4/9/9/9/9/8+b/P8/6P2/8K b g 1"


# --- material ---------------------------------------------------------------


def test_material_startpos_is_even():
    board = cshogi.Board()
    black, white = analysis.material(board)
    assert black == white


def test_material_reflects_gold_advantage():
    # 先手が金1枚多い局面
    board = cshogi.Board()
    board.set_sfen("4k4/9/9/9/9/9/9/9/4K4 b G 1")
    black, white = analysis.material(board)
    assert black - white == 550


# --- attackers(利き計算) -----------------------------------------------------


def test_attackers_startpos_known_squares():
    board = cshogi.Board()
    pieces = board.pieces
    # 5五は双方の利きゼロ
    assert analysis.attackers(pieces, cshogi.BLACK, _sq(5, 5)) == []
    assert analysis.attackers(pieces, cshogi.WHITE, _sq(5, 5)) == []
    # 5八への先手の利き: 金4九・金6九・玉5九・飛2八(横利き)の4つ
    got = sorted(analysis.attackers(pieces, cshogi.BLACK, _sq(5, 8)))
    assert got == sorted([_sq(4, 9), _sq(6, 9), _sq(5, 9), _sq(2, 8)])
    # 1三(後手歩)への後手の紐: 香1一(直射)・桂2一・角2二
    got = sorted(analysis.attackers(pieces, cshogi.WHITE, _sq(1, 3)))
    assert got == sorted([_sq(1, 1), _sq(2, 1), _sq(2, 2)])
    # 走り利きの遮断: 飛2八の横利きは角8八で止まり、9八には届かない
    assert analysis.attackers(pieces, cshogi.BLACK, _sq(9, 8)) == [_sq(9, 9)]  # 玉ではなく香9九の縦利きのみ


def test_attackers_cross_check_with_pseudo_legal_moves():
    """ランダム対局の各局面で、手番側の「取る手」の(from, to)集合と利き計算が一致すること。

    pseudo_legal_movesはピン・自玉が取られる手も生成する(実機確認済み)ため、
    純粋な利きの検証に使える。王手中は回避手のみ生成されるためスキップする。
    """
    rng = random.Random(42)
    board = cshogi.Board()
    checked_positions = 0
    for _ in range(150):
        moves = list(board.legal_moves)
        if not moves or board.is_game_over():
            break
        board.push(rng.choice(moves))
        if board.is_game_over() or board.is_check():
            continue
        pieces = board.pieces
        own = board.turn
        opp_is_white = own == cshogi.BLACK
        expected = set()
        for m in board.pseudo_legal_moves:
            if cshogi.move_is_drop(m):
                continue
            to = cshogi.move_to(m)
            if pieces[to] != 0:
                expected.add((cshogi.move_from(m), to))
        got = set()
        for sq, code in enumerate(pieces):
            if code == 0 or (code >= 16) != opp_is_white:
                continue
            for a in analysis.attackers(pieces, own, sq):
                got.add((a, sq))
        assert got == expected, board.sfen()
        checked_positions += 1
    assert checked_positions > 50  # 検証が空回りしていないこと


# --- attacked_pieces(当たり一覧) ---------------------------------------------


def test_attacked_pieces_lists_hanging_pieces():
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    result = analysis.attacked_pieces(board)
    # 価値の高い順: 銀5五(歩の当たり) → 歩1五(香の当たり)。いずれも紐なし。
    assert [e["square"] for e in result] == ["5五", "1五"]
    silver, pawn = result
    assert silver == {
        "square": "5五", "piece": "銀", "attackers": 1, "defenders": 0,
        "hanging": True, "king_only_defense": False,
        "cheapest_attacker": "歩", "pawn_drop_risk": False,
    }
    assert pawn["piece"] == "歩"
    assert pawn["cheapest_attacker"] == "香"
    assert pawn["hanging"]


def test_attacked_pieces_counts_defenders():
    board = cshogi.Board()
    board.set_sfen(DEFENDED_SFEN)
    (entry,) = analysis.attacked_pieces(board)
    assert entry["square"] == "5五"
    assert entry["defenders"] == 1  # 金5六の紐
    assert not entry["hanging"]


def test_attacked_pieces_empty_at_startpos():
    board = cshogi.Board()
    assert analysis.attacked_pieces(board) == []


def test_attacked_pieces_color_param_defaults_to_side_to_move():
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    assert analysis.attacked_pieces(board, color=cshogi.BLACK) == analysis.attacked_pieces(board)


def test_attacked_pieces_king_only_defense_true():
    # (a) games/2026-07-13_064822.kif、14手目(６五桂、7c6e)の直後の局面の再現。
    # 5七の歩は桂の当たりを受けており、紐は自玉(5八)のみ。
    board = cshogi.Board()
    board.set_sfen(
        "l1sg1gsnl/1r4kb1/pp2pp1pp/2pp2p2/3n3P1/2P6/PPBPPPP1P/2SK3R1/LNG2GSNL b - 15"
    )
    pawn = next(e for e in analysis.attacked_pieces(board) if e["square"] == "5七")
    assert pawn["defenders"] == 1
    assert pawn["king_only_defense"]


def test_attacked_pieces_king_only_defense_false_when_defender_is_not_king():
    # (b) DEFENDED_SFEN: 5五の銀は金5六の紐のみ(玉は無関係)。
    board = cshogi.Board()
    board.set_sfen(DEFENDED_SFEN)
    (entry,) = analysis.attacked_pieces(board)
    assert entry["defenders"] == 1
    assert not entry["king_only_defense"]


# (c) 5五の銀を玉(4六)と金(5六)の両方が守る形。全てが玉ではないためfalse。
KING_ADJACENT_DEFENSE_SFEN = "4k4/9/9/4p4/4S4/4GK3/9/9/9 b - 1"


def test_attacked_pieces_king_only_defense_false_when_king_and_other_piece_defend():
    board = cshogi.Board()
    board.set_sfen(KING_ADJACENT_DEFENSE_SFEN)
    (entry,) = analysis.attacked_pieces(board)
    assert entry["defenders"] == 2
    assert not entry["king_only_defense"]


def test_attacked_pieces_king_only_defense_false_when_hanging():
    # (d) HANGING_SFEN: 紐なし(hanging: True)の駒はking_only_defenseも排他的にFalse。
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    silver, pawn = analysis.attacked_pieces(board)
    assert silver["hanging"] and not silver["king_only_defense"]
    assert pawn["hanging"] and not pawn["king_only_defense"]


def test_attacked_pieces_color_param_reports_other_side():
    # HANGING_SFENは先手番。先手の銀5五・歩1五(白視点では無関係)に加え、
    # 白の歩5四(黒銀の当たり)・香1四(黒歩の当たり)もcolor指定で取得できる。
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    black_side = analysis.attacked_pieces(board, color=cshogi.BLACK)
    white_side = analysis.attacked_pieces(board, color=cshogi.WHITE)
    assert [e["piece"] for e in black_side] == ["銀", "歩"]
    assert [e["square"] for e in white_side] == ["1四", "5四"]


# --- pawn_drop_risk(§15.1: 歩打ちの当たり検知) --------------------------------

# 先手銀5五(盤上の当たりなし)、後手が持ち駒に歩1枚。5四が空いているため打たれる。
PAWN_DROP_RISK_SFEN = "4k4/9/9/9/4S4/9/9/9/4K4 b p 1"

# 上と同型だが、5二に後手の不成の歩が既にある(二歩のため5四には打てない)。
NIFU_BLOCKED_SFEN = "4k4/4p4/9/9/4S4/9/9/9/4K4 b p 1"

# 上と同型だが、5四(打ち込み先)に後手の角があり空いていない。角は同じ筋を直射しない
# ため5五の銀を攻撃せず、「空きマスでない」条件だけを二歩・当たりから独立に検証できる。
OCCUPIED_ORIGIN_SFEN = "4k4/9/9/4b4/4S4/9/9/9/4K4 b p 1"


def test_attacked_pieces_detects_pawn_drop_risk_with_no_board_attackers():
    board = cshogi.Board()
    board.set_sfen(PAWN_DROP_RISK_SFEN)
    (entry,) = analysis.attacked_pieces(board, color=cshogi.BLACK)
    assert entry["square"] == "5五"
    assert entry["attackers"] == 0
    assert entry["cheapest_attacker"] is None
    assert entry["hanging"]
    assert entry["pawn_drop_risk"]


def test_attacked_pieces_pawn_drop_risk_blocked_by_nifu():
    board = cshogi.Board()
    board.set_sfen(NIFU_BLOCKED_SFEN)
    assert analysis.attacked_pieces(board, color=cshogi.BLACK) == []


def test_attacked_pieces_pawn_drop_risk_blocked_by_occupied_origin():
    board = cshogi.Board()
    board.set_sfen(OCCUPIED_ORIGIN_SFEN)
    assert analysis.attacked_pieces(board, color=cshogi.BLACK) == []


def test_attacked_pieces_pawn_drop_risk_false_without_pawn_in_hand():
    # HANGING_SFENは持ち駒なし。盤上の当たりで一覧には載るが歩打ちの脅威はない。
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    silver, _pawn = analysis.attacked_pieces(board)
    assert not silver["pawn_drop_risk"]


def test_pawn_drop_risk_false_when_no_pawn_in_hand():
    pieces = [0] * 81
    assert not analysis._pawn_drop_risk(pieces, cshogi.BLACK, 0, 40)


def test_pawn_drop_risk_true_on_empty_board_with_pawn_in_hand():
    pieces = [0] * 81
    assert analysis._pawn_drop_risk(pieces, cshogi.BLACK, 1, 40)


def test_pawn_drop_risk_false_when_origin_off_board():
    # 段(0始まり)8("九")の駒への先手の歩打ちは、打ち込み先が盤外(段9)になる。
    pieces = [0] * 81
    sq = 2 * 9 + 8
    assert not analysis._pawn_drop_risk(pieces, cshogi.BLACK, 1, sq)


def test_pawn_drop_risk_false_when_origin_occupied():
    pieces = [0] * 81
    sq = 4 * 9 + 4
    origin_sq = 4 * 9 + 5  # 先手attacker: origin_rank = target_rank + 1
    pieces[origin_sq] = cshogi.PAWN
    assert not analysis._pawn_drop_risk(pieces, cshogi.BLACK, 1, sq)


def test_pawn_drop_risk_false_when_nifu_on_file():
    pieces = [0] * 81
    sq = 4 * 9 + 4
    pieces[4 * 9 + 0] = cshogi.PAWN  # 同じ筋(4)に先手の不成の歩が既にある
    assert not analysis._pawn_drop_risk(pieces, cshogi.BLACK, 1, sq)


# --- find_mate / find_mate_threat -------------------------------------------


def test_find_mate_in_1():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    found = analysis.find_mate(board)
    assert found is not None
    move, ply = found
    assert cshogi.move_to_usi(move) == "G*5b"
    assert ply == 1


def test_find_mate_in_3():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_3_SFEN)
    found = analysis.find_mate(board)
    assert found is not None
    move, ply = found
    assert cshogi.move_to_usi(move) == "G*5c"
    assert ply == 3


def test_find_mate_none_at_startpos():
    board = cshogi.Board()
    assert analysis.find_mate(board) is None


def test_find_mate_threat_detects_tsumero():
    board = cshogi.Board()
    board.set_sfen(TSUMERO_SFEN)
    sfen_before = board.sfen()
    found = analysis.find_mate_threat(board)
    assert found is not None
    _, ply = found
    assert ply <= 5
    assert board.sfen() == sfen_before  # push_pass/pop_passで盤面が戻っていること


def test_find_mate_threat_none_at_startpos():
    board = cshogi.Board()
    assert analysis.find_mate_threat(board) is None


def test_find_mate_threat_skipped_in_check():
    board = cshogi.Board()
    board.set_sfen(IN_CHECK_SFEN)
    assert board.is_check()
    assert analysis.find_mate_threat(board) is None


# --- analyze ----------------------------------------------------------------


def test_analyze_startpos():
    board = cshogi.Board()
    result = analysis.analyze(board)
    assert result["material"]["diff_black_minus_white"] == 0
    assert result["hands"] == {"black": {}, "white": {}}
    assert not result["in_check"]
    assert result["mate_for_side_to_move"] is None
    assert result["mate_threat_against_side_to_move"] is None
    assert result["check_evasions"] is None
    assert result["attacked_pieces"] == []


def test_analyze_reports_mate_and_threat():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    result = analysis.analyze(board)
    assert result["mate_for_side_to_move"] == {
        "found": True,
        "within_ply": 1,
        "first_move_usi": "G*5b",
    }

    board.set_sfen(TSUMERO_SFEN)
    result = analysis.analyze(board)
    assert result["mate_threat_against_side_to_move"] is not None


def test_analyze_check_evasions_with_safe_escape():
    # 飛車の王手1本だけなら、どの回避手の後も詰みは残らない
    board = cshogi.Board()
    board.set_sfen(IN_CHECK_SFEN)
    sfen_before = board.sfen()
    result = analysis.analyze(board)
    assert result["in_check"]
    evasions = result["check_evasions"]
    assert evasions is not None
    assert evasions["total"] == len(evasions["safe_usi"]) > 0
    assert not evasions["all_allow_mate"]
    assert board.sfen() == sfen_before  # 盤面が変わっていないこと


def test_analyze_check_evasions_no_escape():
    # どこへ逃げても持ち駒の金で1手詰め=受けなし
    board = cshogi.Board()
    board.set_sfen(NO_ESCAPE_CHECK_SFEN)
    result = analysis.analyze(board)
    assert result["in_check"]
    evasions = result["check_evasions"]
    assert evasions["total"] > 0
    assert evasions["safe_usi"] == []
    assert evasions["all_allow_mate"]


def test_analyze_reports_attacked_pieces():
    board = cshogi.Board()
    board.set_sfen(HANGING_SFEN)
    result = analysis.analyze(board)
    assert [e["piece"] for e in result["attacked_pieces"]] == ["銀", "歩"]


# --- king_safety(§22.4) -------------------------------------------------------

# own_shelter_count検証用: 先手玉5九に、隣接する5八の金・4八の銀(いずれも自分の駒)。
KING_SAFETY_SHELTER_SFEN = "4k4/9/9/9/9/9/9/4GS3/4K4 b - 1"

# opponent_hand_value検証用: 手番(先手)から見た相手(後手)の持ち駒が飛1・歩2。
KING_SAFETY_HAND_VALUE_SFEN = "4k4/9/9/9/9/9/9/9/4K4 b r2p 1"


def test_analyze_king_safety_own_shelter_count():
    # (h) 玉の隣接マスに金銀(成駒含む)を配置した局面で正しい数を返すこと。
    board = cshogi.Board()
    board.set_sfen(KING_SAFETY_SHELTER_SFEN)
    result = analysis.analyze(board)
    assert result["king_safety"]["own_shelter_count"] == 2


def test_analyze_king_safety_opponent_hand_value():
    # (i) 相手の持ち駒価値の合計(HAND_PIECE_VALUESによる期待値)と一致すること。
    board = cshogi.Board()
    board.set_sfen(KING_SAFETY_HAND_VALUE_SFEN)
    result = analysis.analyze(board)
    assert result["king_safety"]["opponent_hand_value"] == 1000 + 2 * 100


def test_analyze_king_safety_present_while_in_check():
    # (j) 王手中でもmajor_piece_drop_threats等と異なり空にならず、通常どおり計算される。
    board = cshogi.Board()
    board.set_sfen(IN_CHECK_SFEN)
    result = analysis.analyze(board)
    assert result["in_check"]
    assert result["king_safety"] == {"own_shelter_count": 0, "opponent_hand_value": 0}


# --- 玉の安全度(king safety) -------------------------------------------------


def test_eval_penalizes_exposed_king():
    # 材料は同じ(後手飛1枚)。飛車が玉頭側の利きを持つ局面の方が評価が低いこと。
    exposed = cshogi.Board()
    exposed.set_sfen(KING_EXPOSED_SFEN)
    safe = cshogi.Board()
    safe.set_sfen(KING_SAFE_SFEN)
    # depth=0: 取る手がない局面なので静的評価がそのまま返る
    score_exposed = analysis.search_material(exposed, depth=0)["score"]
    score_safe = analysis.search_material(safe, depth=0)["score"]
    assert score_exposed < score_safe


# --- _king_shelter_count(玉の隣接金銀カウント、§22.1) -------------------------


def test_king_shelter_count_counts_adjacent_own_gold_silver_and_promoted():
    # (a) 隣接する金・銀・と金(金と同格の成駒)は数え、隣接しない駒・敵駒・
    # 対象外の駒種(桂)は数えないこと。
    pieces = [0] * 81
    king_sq = _sq(5, 5)
    pieces[_sq(5, 4)] = cshogi.GOLD          # 隣接・自分の金
    pieces[_sq(4, 5)] = cshogi.SILVER        # 隣接・自分の銀
    pieces[_sq(6, 6)] = cshogi.PROM_PAWN     # 隣接・自分のと金(金と同格)
    pieces[_sq(6, 5)] = cshogi.GOLD + 16     # 隣接・相手の金(対象外)
    pieces[_sq(4, 6)] = cshogi.KNIGHT        # 隣接・自分の桂(対象外の駒種)
    pieces[_sq(5, 3)] = cshogi.GOLD          # 非隣接・自分の金(対象外)
    assert analysis._king_shelter_count(pieces, cshogi.BLACK, king_sq) == 3


# --- 反復深化(iterative deepening, §14.4) -------------------------------------


def test_search_material_completes_full_depth_with_ample_budget():
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    result = analysis.search_material(board, depth=3, node_limit=analysis.DEFAULT_NODE_LIMIT)
    assert result["completed_depth"] == 3
    assert not result["truncated"]
    assert result["score"] is not None


def test_search_material_reports_zero_completed_depth_on_tiny_budget():
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    result = analysis.search_material(board, depth=3, node_limit=1)
    assert result["completed_depth"] == 0
    assert result["truncated"]
    assert result["score"] is None
    assert result["pv_usi"] == []


def test_search_material_keeps_last_completed_depth_when_next_is_truncated():
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    result = analysis.search_material(board, depth=3, node_limit=5)
    # 深さ1は完了したが、予算5では深さ2以降が打ち切られ、その結果は捨てられること
    assert 0 <= result["completed_depth"] < 3
    if result["completed_depth"] == 0:
        assert result["score"] is None
    else:
        assert result["truncated"]


# --- verify_moves -----------------------------------------------------------


def test_verify_moves_rejects_illegal():
    board = cshogi.Board()
    results = analysis.verify_moves(board, ["7g7e", "G*5e", "7g7f"])
    assert results[0] == {"usi": "7g7e", "legal": False}
    assert results[1] == {"usi": "G*5e", "legal": False}
    assert results[2]["legal"]


def test_verify_moves_detects_mate_move():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    (entry,) = analysis.verify_moves(board, ["G*5b"])
    assert entry["is_mate"]


def test_verify_moves_flags_blunder_negative():
    board = cshogi.Board()
    board.set_sfen(BLUNDER_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5d"])
    assert entry["captures"] == "歩"
    assert entry["material_change"] < -500  # 歩を取っても飛車を取り返されて大損


def test_verify_moves_free_capture_positive():
    board = cshogi.Board()
    board.set_sfen(FREE_GOLD_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5c+"])
    assert entry["captures"] == "金"
    assert entry["material_change"] > 500


def test_verify_moves_detects_fork():
    board = cshogi.Board()
    board.set_sfen(FORK_SFEN)
    (entry,) = analysis.verify_moves(board, ["6g5e"])
    # 両取り: 後手が最善の受け(飛5cで金に紐付け)をしても桂金交換で駒得(深さ3で検出できること)
    assert entry["material_change"] >= 400


def test_verify_moves_detects_sudden_death():
    board = cshogi.Board()
    board.set_sfen(SUDDEN_DEATH_SFEN)
    results = analysis.verify_moves(board, ["G*1e", "G*5h"], mate_ply=3)
    careless, defend = results
    assert careless["allows_mate"] is not None  # 放置すると△G*5hで頓死
    assert careless["allows_mate"]["within_ply"] == 1
    assert defend["allows_mate"] is None  # 5hに金を打てば受かる


def test_verify_moves_does_not_mutate_board():
    board = cshogi.Board()
    sfen_before = board.sfen()
    analysis.verify_moves(board, ["7g7f", "2g2f"])
    assert board.sfen() == sfen_before


# --- destination / own_attacked_after(§14.3) ---------------------------------


def test_verify_moves_warns_undefended_drop_into_opponent_effects():
    # 実対局の再現ケース: 馬の利きにある3四への桂打ちがdestinationで警告されること。
    board = cshogi.Board()
    board.set_sfen(UNDEFENDED_DROP_SFEN)
    (entry,) = analysis.verify_moves(board, ["N*3d"])
    assert entry["destination"] == {"square": "3四", "opponent_effects": 1, "own_supports": 0}
    # 打った桂自身が着手直後に馬に当たっていること
    assert [e["square"] for e in entry["own_attacked_after"]] == ["3四"]
    assert entry["own_attacked_after"][0]["hanging"]


def test_verify_moves_defended_drop_has_own_support():
    board = cshogi.Board()
    board.set_sfen(DEFENDED_DROP_SFEN)
    (entry,) = analysis.verify_moves(board, ["N*3d"])
    assert entry["destination"] == {"square": "3四", "opponent_effects": 1, "own_supports": 1}
    assert not entry["own_attacked_after"][0]["hanging"]


def test_verify_moves_own_attacked_after_reflects_king_only_defense():
    # (e) verify_movesのown_attacked_afterも共通関数(attacked_pieces)を経由するため
    # king_only_defenseが反映されること。
    board = cshogi.Board()
    board.set_sfen(KING_ONLY_DEFENSE_DROP_SFEN)
    (entry,) = analysis.verify_moves(board, ["N*3d"])
    assert entry["own_attacked_after"][0]["king_only_defense"]


def test_verify_moves_is_mate_candidate_has_no_destination():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    (entry,) = analysis.verify_moves(board, ["G*5b"])
    assert "destination" not in entry
    assert "own_attacked_after" not in entry
    assert "major_piece_drop_threats_after" not in entry
    assert "trapped_major_pieces_after" not in entry
    assert "own_trapped_major_pieces_after" not in entry  # (h) §21.4
    assert "own_king_shelter_after" not in entry  # (d) §22.6
    assert "own_attacked_after_pv" not in entry  # §24.5
    assert "mate_threat_after_pv" not in entry  # §24.5
    assert "opponent_fork_threats_after" not in entry  # (d) §25.5


# --- verify_movesのown_trapped_major_pieces_after(§21.2, §21.4(f)(g)) ----------

# (f) 自分の角を、合法な移動先が完全に塞がれたマス(9九、直前に先手歩8八が
# 唯一の逃げ道を塞ぐ)へ打つ候補。着手直後、角は動けず捕獲確定になる。
OWN_TRAPPED_AFTER_DROP_SFEN = "9/9/9/9/4K3k/9/9/1P7/9 b B 1"

# (g) 同型だが着地点を開けたマス(5七)にする、通常の安全な候補。
OWN_TRAPPED_AFTER_SAFE_SFEN = OWN_TRAPPED_AFTER_DROP_SFEN


def test_verify_moves_own_trapped_major_pieces_after_detects_self_trap():
    board = cshogi.Board()
    board.set_sfen(OWN_TRAPPED_AFTER_DROP_SFEN)
    (entry,) = analysis.verify_moves(board, ["B*9i"])
    trapped = next(
        (e for e in entry["own_trapped_major_pieces_after"] if e["square"] == "9九"), None
    )
    assert trapped is not None
    assert trapped["piece"] == "角"
    assert trapped["legal_move_count"] == 0


def test_verify_moves_own_trapped_major_pieces_after_empty_on_safe_candidate():
    board = cshogi.Board()
    board.set_sfen(OWN_TRAPPED_AFTER_SAFE_SFEN)
    (entry,) = analysis.verify_moves(board, ["B*5g"])
    assert entry["own_trapped_major_pieces_after"] == []


# --- verify_movesのopponent_fork_threats_after(§25.1, §25.5(c)(d)) -----------

# games/2026-07-17_074805.kif 31手目相当(黒の8i7gの直前)の実戦再現。
# 候補8i7g(黒桂が7七のと金を取る)を指した直後、白は持ち駒の角をB*6fに打つと
# 王手であると同時に着地したばかりの黒桂7七に当たる(玉以外の当たりは1駒のみ
# だが、王手そのものを1駒分の当たりとして数えるため両取りとして検出される)。
OPPONENT_FORK_THREAT_REAL_GAME_SFEN = (
    "ln1gkgsnl/3r5/ppp1pp1p1/6p1p/7P1/2P1P4/PP+p2PP1P/4SK1R1/LN3GSNL b BSbgp 31"
)

# 上と同型だが白の持ち駒から角を除いた形: 王手両取りが成立しないこと。
OPPONENT_FORK_THREAT_NONE_SFEN = (
    "ln1gkgsnl/3r5/ppp1pp1p1/6p1p/7P1/2P1P4/PP+p2PP1P/4SK1R1/LN3GSNL b BSgp 31"
)


def test_verify_moves_opponent_fork_threats_after_detects_check_and_capture():
    # (c) 候補手を指した直後、相手の角打ちが王手と同時に別の駒への当たりを
    # 成立させる実戦局面(§25.5(c))。
    board = cshogi.Board()
    board.set_sfen(OPPONENT_FORK_THREAT_REAL_GAME_SFEN)
    (entry,) = analysis.verify_moves(board, ["8i7g"])
    threat = next(
        (e for e in entry["opponent_fork_threats_after"] if e["example_move_usi"] == "B*6f"),
        None,
    )
    assert threat is not None
    assert threat["piece"] == "角"
    assert threat["source"] == "drop"
    assert {t["square"] for t in threat["targets"]} == {"7七"}


def test_verify_moves_opponent_fork_threats_after_empty_without_bishop_in_hand():
    # (c) 相手が角を持っていない場合、角打ちによる王手両取りは成立しないこと
    # (盤上の飛車移動による、王手を伴わない別種の両取りは対象外のため残る)。
    board = cshogi.Board()
    board.set_sfen(OPPONENT_FORK_THREAT_NONE_SFEN)
    (entry,) = analysis.verify_moves(board, ["8i7g"])
    assert not any(e["example_move_usi"] == "B*6f" for e in entry["opponent_fork_threats_after"])


def test_verify_moves_opponent_fork_threats_after_excludes_default_check_only():
    # (c) 既定(include_checks=False)のmajor_piece_fork_opportunitiesでは
    # 同じ手が王手のため対象外になること(opponent_fork_threats_afterとの対比)。
    board = cshogi.Board()
    board.set_sfen(OPPONENT_FORK_THREAT_REAL_GAME_SFEN)
    board.push(board.move_from_usi("8i7g"))
    result = analysis.major_piece_fork_opportunities(board, color=cshogi.WHITE)
    assert not any(e["example_move_usi"] == "B*6f" for e in result)


# --- verify_movesのown_king_shelter_after(§22.2, §22.6(b)(c)(e)) --------------


def test_verify_moves_own_king_shelter_after_decreases_along_pv():
    # (b) games/2026-07-15_182533.kif 34手目相当の再現局面。▲5五歩は着手直後は
    # 玉の守備駒数に変化がないが、読み筋を最後まで適用すると隣接の金が釣り出されて
    # immediately_afterよりafter_pvが減ること。
    board = cshogi.Board()
    board.set_sfen(KING_SHELTER_PV_DECREASE_SFEN)
    (entry,) = analysis.verify_moves(board, ["5f5e"])
    shelter = entry["own_king_shelter_after"]
    assert shelter["after_pv"] is not None
    assert shelter["after_pv"] < shelter["immediately_after"]


def test_verify_moves_own_king_shelter_after_pv_is_none_on_zero_depth():
    # (c) search_depth_completed == 0のとき、after_pvがnullであること
    # (material_changeがnullになる場合と同じ扱い)。
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    (entry,) = analysis.verify_moves(board, ["5i5h"], node_limit=1)
    assert entry["search_depth_completed"] == 0
    assert entry["own_king_shelter_after"]["after_pv"] is None


def test_verify_moves_own_king_shelter_after_reflects_king_move_itself():
    # (e) 候補手が玉の移動そのものである場合、immediately_afterが移動後の玉の
    # 位置を基準に正しく評価されること。games/2026-07-15_182533.kif 66手目
    # (△7八金打)の王手直後、黒玉が9九へ逃げる候補(8h9i)の再現。
    board = cshogi.Board()
    board.set_sfen(KING_MOVES_ITSELF_SFEN)
    (entry,) = analysis.verify_moves(board, ["8h9i"])
    b2 = cshogi.Board()
    b2.set_sfen(KING_MOVES_ITSELF_SFEN)
    b2.push(b2.move_from_usi("8h9i"))
    expected = analysis._king_shelter_count(
        b2.pieces, cshogi.BLACK, b2.king_square(cshogi.BLACK)
    )
    assert entry["own_king_shelter_after"]["immediately_after"] == expected


# --- verify_movesのown_attacked_after_pv/mate_threat_after_pv(§24.2, §24.3) ---


def test_verify_moves_own_attacked_after_pv_detects_new_attack_along_pv():
    # (e) §24.5: own_attacked_after(着手直後、応手を読む前)には現れない、
    # 読み筋の途中で自分の駒に新たに生じる当たりがown_attacked_after_pvで
    # 検出されること。
    board = cshogi.Board()
    board.set_sfen(OWN_ATTACKED_AFTER_PV_SFEN)
    (entry,) = analysis.verify_moves(board, ["1g1f"], depth=1)
    assert entry["search_depth_completed"] > 0
    assert "7七" not in [e["square"] for e in entry["own_attacked_after"]]
    assert "7七" in [e["square"] for e in entry["own_attacked_after_pv"]]


def test_verify_moves_own_attacked_after_pv_is_none_on_zero_depth():
    # (f) search_depth_completed == 0のとき、own_attacked_after_pvがnullで
    # あること(material_changeがnullになる場合と同じ扱い)。
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    (entry,) = analysis.verify_moves(board, ["5i5h"], node_limit=1)
    assert entry["search_depth_completed"] == 0
    assert entry["own_attacked_after_pv"] is None


def test_verify_moves_mate_threat_after_pv_detects_new_threat():
    # (g) §24.5: 読み筋を最後まで適用する前は詰めろが存在しないが、適用後に
    # 詰めろが生じる局面でmate_threat_after_pvが正しく検出されること。
    board = cshogi.Board()
    board.set_sfen(MATE_THREAT_AFTER_PV_SFEN)
    assert analysis.find_mate_threat(cshogi.Board(MATE_THREAT_AFTER_PV_SFEN), 5) is None
    (entry,) = analysis.verify_moves(board, ["9g9f"], depth=1, mate_ply=5)
    assert entry["search_depth_completed"] > 0
    assert entry["allows_mate"] is None  # 候補手自体は頓死ではないこと
    threat = entry["mate_threat_after_pv"]
    assert threat is not None
    assert threat["found"] is True
    assert threat["within_ply"] == 1


def test_verify_moves_mate_threat_after_pv_none_when_no_threat():
    # (h) 読み筋終端で詰めろがない場合Noneになること。
    board = cshogi.Board()
    board.set_sfen(CAPTURE_ROOK_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5c"])
    assert entry["search_depth_completed"] > 0
    assert entry["mate_threat_after_pv"] is None


def test_verify_moves_mate_threat_after_pv_is_none_on_zero_depth():
    # (h) search_depth_completed == 0のとき、mate_threat_after_pvがnullである
    # こと。
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    (entry,) = analysis.verify_moves(board, ["5i5h"], node_limit=1)
    assert entry["search_depth_completed"] == 0
    assert entry["mate_threat_after_pv"] is None


def test_verify_moves_mate_threat_after_pv_none_when_pv_length_is_even():
    # 実戦局面(games/2026-07-16_074057.kif 57手目相当)の再現で判明した既知の
    # 限界: 読み筋の総手数が偶数だと読み筋終端の手番がこの手を指した側
    # (mover_color)に戻らず相手番のままになる(反復深化の打ち切り・静止探索の
    # 追加の取り合いで発生しうる)。この場合find_mate_threatを素直に呼ぶと
    # 逆方向(相手が何もしなければこの手を指した側が詰ませられるか)の判定に
    # なってしまうため、mate_threat_after_pvはnullを返すこと
    # (MATE_THREAT_AFTER_PV_SFENは詰めろの土台〈馬+持ち駒金〉自体はdepth=1と
    # 変わらず残っているが、depth=2では読み筋が2手〈偶数〉になり手番が
    # 戻らないことを利用する)。
    board = cshogi.Board()
    board.set_sfen(MATE_THREAT_AFTER_PV_SFEN)
    (entry,) = analysis.verify_moves(board, ["9g9f"], depth=2, mate_ply=5)
    assert entry["search_depth_completed"] > 0
    assert len(entry["reply_pv_usi"]) % 2 == 0
    assert entry["mate_threat_after_pv"] is None


# --- 反復深化がverify_movesの信頼性判断に反映されること(§14.4) -----------------


# --- verify_movesの候補手プレビュー(§20.2, §20.5(d)(e)) -----------------------

# (d) games/2026-07-13_201007.kif、33手目(1八香、1i1h)を指す前の局面の再現。
# この手は1九マスを空け、新たな角打ち・成り込みの脅威を自ら生む(振り返りで判明)。
VERIFY_PREVIEW_PLY33_SFEN = (
    "l6nl/1r2ggk2/pp1spp1sp/2pp2pp1/9/2PP5/PPS2PP1P/1GK2S1R1/LN3G1NL b BNb2p 33"
)

# (e) 同KIF、47手目相当の局面の再現。実戦では無難な香上がりを指したが、5八飛
# (2h5h)を指すだけで後手の角(5七、trapped_major_piecesで退避不可と判定済み)を
# 直接の当たり(紐なし)にできた。
VERIFY_PREVIEW_PLY47_SFEN = (
    "l7l/3r1gk2/p3pgnsp/1pppsppp1/9/2PP1PP2/PPS1bS2P/1GK4RL/LN3G1NB b N2p 47"
)


def test_verify_moves_major_piece_drop_threats_after_detects_new_threat():
    board = cshogi.Board()
    board.set_sfen(VERIFY_PREVIEW_PLY33_SFEN)
    (entry,) = analysis.verify_moves(board, ["1i1h"])
    assert any(e["square"] == "1九" for e in entry["major_piece_drop_threats_after"])


def test_verify_moves_trapped_major_pieces_after_detects_capture_opportunity():
    board = cshogi.Board()
    board.set_sfen(VERIFY_PREVIEW_PLY47_SFEN)
    (entry,) = analysis.verify_moves(board, ["2h5h"])
    trapped = next(
        (e for e in entry["trapped_major_pieces_after"] if e["square"] == "5七"), None
    )
    assert trapped is not None
    assert trapped["piece"] == "角"
    assert trapped["attackers"] >= 1


def test_verify_moves_reports_zero_search_depth_completed_on_tiny_budget():
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    (entry,) = analysis.verify_moves(board, ["5i5h"], node_limit=1)
    assert entry["search_depth_completed"] == 0
    assert entry["search_truncated"]
    assert entry["material_change"] is None
    assert entry["reply_pv_usi"] == []


# --- major_piece_trade(§16.1, §16.3) -----------------------------------------


def test_major_piece_trade_true_when_candidate_captures_rook():
    board = cshogi.Board()
    board.set_sfen(CAPTURE_ROOK_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5c"])
    assert entry["captures"] == "飛"
    assert entry["major_piece_trade"]


def test_major_piece_trade_false_on_quiet_move_without_major_pieces():
    board = cshogi.Board()
    board.set_sfen(QUIET_NO_MAJOR_PIECE_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5d"])
    assert entry["captures"] is None
    assert not entry["major_piece_trade"]


def test_major_piece_trade_true_when_own_rook_is_captured_in_pv():
    board = cshogi.Board()
    board.set_sfen(PV_CAPTURES_OWN_ROOK_SFEN)
    (entry,) = analysis.verify_moves(board, ["9g9f"])
    assert entry["captures"] is None  # 候補手自体は捕り駒なし
    assert entry["search_depth_completed"] > 0
    assert entry["reply_pv_usi"]
    assert entry["major_piece_trade"]  # 読み筋の中で自分の飛が捕られる


def test_major_piece_trade_false_on_mate_move_without_major_capture():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    (entry,) = analysis.verify_moves(board, ["G*5b"])
    assert entry["is_mate"]
    assert entry["reply_pv_usi"] == []
    assert not entry["major_piece_trade"]


def test_major_piece_trade_false_on_zero_depth_when_candidate_has_no_capture():
    board = cshogi.Board()
    board.set_sfen(KING_EXPOSED_SFEN)
    (entry,) = analysis.verify_moves(board, ["5i5h"], node_limit=1)
    assert entry["search_depth_completed"] == 0
    assert not entry["major_piece_trade"]


def test_major_piece_trade_true_when_candidate_captures_promoted_rook():
    board = cshogi.Board()
    board.set_sfen(CAPTURE_DRAGON_SFEN)
    (entry,) = analysis.verify_moves(board, ["5e5c"])
    assert entry["captures"] == "飛"  # 龍は不成の飛として持ち駒に入る(既存仕様)
    assert entry["major_piece_trade"]


# --- major_piece_drop_threats(§17.1, §17.3) ---------------------------------

# パターンA(王手+紐なし駒への当たり)用: 先手玉9一、後手玉1九、後手持ち駒に飛。
# 先手銀2八(紐なし)。▲飛打5八→(2手パス想定)→△5八9八+ が9一玉に王手をかけつつ
# 5八8→2八ラインで銀にも当たる(直接の打ち込みは玉と同筋/同段でないため王手にならない)。
DROP_THREAT_PATTERN_A_SFEN = "K8/9/9/9/9/9/9/7S1/8k b r 1"

# パターンB(王手+安全な移動先)用: 紐なし駒を置かず、9一玉との整合だけを用意。
DROP_THREAT_PATTERN_B_SFEN = "K8/9/9/9/9/9/9/9/8k b r 1"

# パターンC(王手なし+紐なし駒を2つ同時に当てる=両取り)用: 先手銀5一(5八と同じ筋)・
# 先手銀1五(5八からの移動先と同じ段になりうる)を用意。
DROP_THREAT_PATTERN_C_SFEN = "K3S4/9/9/9/8S/9/9/9/8k b r 1"

# パターンD(王手なし+紐なし駒への当たり+安全な移動先)用: 紐なし駒を1つだけ用意。
DROP_THREAT_PATTERN_D_SFEN = "K8/9/9/9/8S/9/9/9/8k b r 1"

# (e) 打ち込みマスに手番側の利きがある(先手金5九が5八を守る)→前提条件で除外。
DROP_THREAT_DEFENDED_SQUARE_SFEN = "K8/9/9/9/9/9/9/9/4G3k b r 1"

# (f)/そのほか: 玉の整合だけを持つ静かな盤面(打ち込みマス自体は個別に指定して使う)。
DROP_THREAT_OPEN_SFEN = "K8/9/9/9/9/9/9/9/8k b r 1"

# (h) 手番側(先手)が王手中 → push_pass不可のため空リスト。
DROP_THREAT_IN_CHECK_SFEN = "4K4/9/4r4/9/9/9/9/9/k8 b r 1"

# (i) 打ち込み自体が直接王手になる候補(先手玉5一と同じ筋の5八への飛打ち)。
DROP_THREAT_DIRECT_CHECK_SFEN = "4K4/9/9/9/9/9/9/9/8k b r 1"

# (j) 自陣3段目以内が自駒(銀)で完全に埋まっている→候補マスなし(持ち駒に飛はある)。
DROP_THREAT_NO_CANDIDATES_SFEN = "K8/9/9/9/9/9/SSSSSSSSS/SSSSSSSSS/SSSSSSSSk b r 1"


def test_major_piece_drop_threats_detects_pattern_a():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_A_SFEN)
    entry = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 8), cshogi.ROOK)
    assert entry is not None
    assert entry["square"] == "5八"
    assert entry["piece"] == "飛"
    assert "A" in entry["patterns"]


def test_major_piece_drop_threats_detects_pattern_b():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_B_SFEN)
    entry = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 8), cshogi.ROOK)
    assert entry is not None
    assert entry["patterns"] == ["B"]  # 紐なし駒がないためA/C/Dは付かない


def test_major_piece_drop_threats_detects_pattern_c():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_C_SFEN)
    entry = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 8), cshogi.ROOK)
    assert entry is not None
    assert "C" in entry["patterns"]


def test_major_piece_drop_threats_detects_pattern_d():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_D_SFEN)
    entry = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 8), cshogi.ROOK)
    assert entry is not None
    assert "D" in entry["patterns"]


def test_major_piece_drop_threats_excludes_defended_square():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_DEFENDED_SQUARE_SFEN)
    assert analysis.attackers(board.pieces, cshogi.BLACK, _sq(5, 8))  # 前提: 5八は紐あり
    result = analysis.major_piece_drop_threats(board)
    assert "5八" not in [e["square"] for e in result]


def test_major_piece_drop_threats_excludes_square_before_third_rank():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_OPEN_SFEN)
    # 直接呼び出しでは5六(4段目)も脅威として成立することを確認したうえで、
    # 全体スキャンでは対象外(自陣3段目=7-9段のみ走査)であることを確認する。
    direct = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 6), cshogi.ROOK)
    assert direct is not None
    result = analysis.major_piece_drop_threats(cshogi.Board(DROP_THREAT_OPEN_SFEN))
    assert "5六" not in [e["square"] for e in result]
    assert "5七" in [e["square"] for e in result]  # 7段目は対象内であることの対照確認


def test_major_piece_drop_threats_empty_without_major_piece_in_hand():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_OPEN_SFEN.replace(" r ", " - "))
    assert analysis.major_piece_drop_threats(board) == []


def test_major_piece_drop_threats_empty_while_in_check():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_IN_CHECK_SFEN)
    assert board.is_check()
    assert analysis.major_piece_drop_threats(board) == []


def test_major_piece_drop_threats_skips_candidate_that_is_itself_check():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_DIRECT_CHECK_SFEN)
    before = board.sfen()
    entry = analysis._check_drop_threat(board, cshogi.BLACK, cshogi.WHITE, _sq(5, 8), cshogi.ROOK)
    assert entry is None
    assert board.sfen() == before  # push/popが対になっており盤面が復元されること


def test_major_piece_drop_threats_empty_when_back_ranks_fully_occupied():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_NO_CANDIDATES_SFEN)
    assert analysis.major_piece_drop_threats(board) == []


def test_major_piece_drop_threats_does_not_mutate_board():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_A_SFEN)
    before = board.sfen()
    analysis.major_piece_drop_threats(board)
    assert board.sfen() == before


def test_analyze_includes_major_piece_drop_threats():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_A_SFEN)
    result = analysis.analyze(board)
    assert any(e["square"] == "5八" for e in result["major_piece_drop_threats"])


# --- major_piece_drop_threatsのcolor引数(§20.1, §20.5(a)(b)) -----------------


def test_major_piece_drop_threats_color_defaults_to_side_to_move():
    # (a) 後方互換性: board.turnと一致するcolorを明示しても従来どおりの結果になること。
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_D_SFEN)
    assert analysis.major_piece_drop_threats(board, color=cshogi.BLACK) == (
        analysis.major_piece_drop_threats(board)
    )


def test_major_piece_drop_threats_color_skips_initial_pass_when_turn_shifted():
    # (b) verify_movesが候補手をpushした直後を模した局面: 手番は既に相手(opp_color)
    # だが、防御側(own_color)は引き続きBLACKとして同じ脅威を検出できること
    # (最初のpush_passが1回少ない状態でも正しく判定できることの確認)。
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_D_SFEN)
    expected = analysis.major_piece_drop_threats(board, color=cshogi.BLACK)

    shifted = cshogi.Board()
    shifted.set_sfen(DROP_THREAT_PATTERN_D_SFEN.replace(" b ", " w "))
    assert analysis.major_piece_drop_threats(shifted, color=cshogi.BLACK) == expected


# --- major_piece_drop_threatsのsource(§21.1) ---------------------------------


def test_major_piece_drop_threats_full_scan_entries_are_tagged_drop_source():
    # (a) 既存の打ち込み由来のエントリ全件にsource: "drop"が付くこと(後方互換性の
    # 維持確認。戻り値の形が変わるため全件確認が必要)。
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_A_SFEN)
    result = analysis.major_piece_drop_threats(board)
    assert result
    assert all(e["source"] == "drop" for e in result)


def test_analyze_major_piece_drop_threats_entries_are_tagged_drop_source():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_PATTERN_A_SFEN)
    result = analysis.analyze(board)
    assert all(e["source"] == "drop" for e in result["major_piece_drop_threats"])


# --- 盤上の未成り大駒前進による成り込み脅威検出(§21.1, §21.4(b)(c)(d)) ---------

# 白の飛が(2,4)から(2,X)へ前進+成りすることで、自陣3段目以内(rank7-9)に達し
# 各パターンを実現できる局面。先手玉・後手玉は無関係な位置に離して配置する。

# パターンB(王手のみ): 2四飛→2八竜が先手玉(5,8)と同じ段(8段目)に達して王手。
BOARD_ADVANCE_PATTERN_B_SFEN = "8k/9/9/7r1/9/9/9/4K4/9 b - 1"

# パターンA(王手+紐なし駒への当たり): 上に加え、後手の当たりを受ける先手銀3七を配置。
# 2四飛→2七竜が3七の銀に当たりつつ王手(2七は5,8と同じ8段目ではないが、
# 2七竜の紐なし判定は別マス、王手は7段目に達した2七竜からは生じない場合もあるため
# 実際の判定は_board_advance_threatsの全候補手の和集合で成立する)。
BOARD_ADVANCE_PATTERN_A_SFEN = "8k/9/9/7r1/9/9/6S2/4K4/9 b - 1"

# パターンD(王手なし+紐なし駒への当たり+安全な移動先): 先手玉を5一に離し、
# 2四飛の前進先である2七竜が3八の銀に当たるが王手にはならない配置。
BOARD_ADVANCE_PATTERN_D_SFEN = "4K3k/9/9/7r1/9/9/9/6S2/9 b - 1"

# パターンC(王手なし+紐なし駒を2つ同時に当てる): 上に加え、2四飛の前進で
# 2七竜が3七・3九の銀2枚に同時に当たる配置(3九へは2七竜の縦利きが届く)。
BOARD_ADVANCE_PATTERN_C_SFEN = "4K3k/9/9/7r1/9/9/6S2/9/6S2 b - 1"


def test_board_advance_threats_detects_pattern_b():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_B_SFEN)
    result = analysis.major_piece_drop_threats(board)
    entry = next(e for e in result if e["square"] == "2四")
    assert entry["source"] == "board"
    assert entry["piece"] == "飛"
    assert "B" in entry["patterns"]


def test_board_advance_threats_detects_pattern_a():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_A_SFEN)
    result = analysis.major_piece_drop_threats(board)
    entry = next(e for e in result if e["square"] == "2四")
    assert "A" in entry["patterns"]


def test_board_advance_threats_detects_pattern_d():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_D_SFEN)
    result = analysis.major_piece_drop_threats(board)
    entry = next(e for e in result if e["square"] == "2四")
    assert "D" in entry["patterns"]


def test_board_advance_threats_detects_pattern_c():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_C_SFEN)
    result = analysis.major_piece_drop_threats(board)
    entry = next(e for e in result if e["square"] == "2四")
    assert "C" in entry["patterns"]


def test_board_advance_threats_excludes_promoted_piece():
    # (c) 既に成っている駒(龍)は「成り込み」の前提に該当しないため対象外。
    board = cshogi.Board()
    sfen = BOARD_ADVANCE_PATTERN_B_SFEN.replace("r", "+r")
    board.set_sfen(sfen)
    result = analysis.major_piece_drop_threats(board)
    assert result == []


def test_board_advance_threats_empty_without_rook_or_bishop_on_board():
    board = cshogi.Board()
    board.set_sfen(DROP_THREAT_OPEN_SFEN.replace(" r ", " - "))
    assert analysis.major_piece_drop_threats(board) == []


def test_board_advance_threats_does_not_mutate_board():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_B_SFEN)
    before = board.sfen()
    analysis.major_piece_drop_threats(board)
    assert board.sfen() == before


def test_board_advance_threats_color_defaults_to_side_to_move():
    # (d) 打ち込み版(§20.5(a))と同じ後方互換性確認。
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_B_SFEN)
    assert analysis.major_piece_drop_threats(board, color=cshogi.BLACK) == (
        analysis.major_piece_drop_threats(board)
    )


def test_board_advance_threats_color_skips_initial_pass_when_turn_shifted():
    # (d) 打ち込み版(§20.5(b))と同じ、手番ずれケースの確認。
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_PATTERN_B_SFEN)
    expected = analysis.major_piece_drop_threats(board, color=cshogi.BLACK)

    shifted = cshogi.Board()
    shifted.set_sfen(BOARD_ADVANCE_PATTERN_B_SFEN.replace(" b ", " w "))
    assert analysis.major_piece_drop_threats(shifted, color=cshogi.BLACK) == expected


# --- games/2026-07-15_060917.kif 26手目の実戦再現(§21.4(e)) --------------------

# 白が６七角打を指した直後(手番は先手)の局面(KIFの26手目を適用した後、
# cshogi.KIF.Parserで再現)。この角は次の一手で自陣後方へ成り込み、以降盤上を
# 動き回る厄介な駒になった(振り返りで判明)。
BOARD_ADVANCE_GAME_REPLAY_SFEN = (
    "lnsg2snl/1r3kg2/p1p1pp1pp/6p2/3P5/1PP6/P1NbPPP1P/5S1R1/L1SGKG1NL b B3P 27"
)


def test_board_advance_threats_detects_2026_07_15_ply26_replay():
    board = cshogi.Board()
    board.set_sfen(BOARD_ADVANCE_GAME_REPLAY_SFEN)
    result = analysis.major_piece_drop_threats(board)
    entry = next((e for e in result if e["square"] == "6七" and e["source"] == "board"), None)
    assert entry is not None
    assert entry["piece"] == "角"


# --- trapped_major_pieces(§18.1, §18.3) --------------------------------------

# (a) games/2026-07-12_181507.kif、26手目(３七角打)の直後に２九飛(2h2i)を指した
# 局面の再現。角(3七)の合法な移動先6通り(1i/2f/2h/4f/4h/5i、成りを含め全6通り)
# 全てに手番側(先手)の利きが及んでおり、退避できない(実際の対局はこの手を候補に
# 含めず、より損な１八飛を選んで後に敗着となった)。
# trapped_major_pieces(board)はboard.turnを「攻撃側(own_color)」として扱うため、
# 2h2iを指した直後の実局面(手番は後手)そのままでは攻撃側/被害側が逆になり、
# 後手の角ではなく先手の飛が判定対象になってしまう。本関数は「攻撃側が実際に
# 指せる相手の合法手」をpush_passで1手先読みする設計(既存のmajor_piece_drop_threats
# と同じ)のため、駒の配置は2h2iを指した直後のまま、手番だけを先手に戻して
# 再現する(先手が何もしない=push_passと仮定した場合の後手の実際の合法手を見る)。
TRAPPED_BISHOP_SFEN = (
    "ln1g3nl/1r3kgs1/1ppspp1p1/p2p2p2/7Np/2P2PPP1/PPSPPSb1P/2GK5/LN3G1RL b B 28"
)

# (e)(f)(g) 白の馬(成角)を9一の隅に置き、8一・9二・8二を白の銀で塞いで
# 合法な移動先を0にした盤面(完全に動けない駒)。(f)用に、同じ構図を先後反転した
# 盤面(手番側自身の馬)も用意する。
TRAPPED_PROMOTED_ZERO_MOVES_SFEN = "+bs7/ss7/9/9/9/9/9/9/K7k b - 1"
TRAPPED_OWN_PROMOTED_NOT_TARGETED_SFEN = "+Bs7/ss7/9/9/9/9/9/9/K7k b - 1"

# (d) 相手(後手)が飛・角(成りを含む)を盤上に一つも持たない盤面。
TRAPPED_NO_MAJOR_PIECE_SFEN = "K8/9/9/9/9/9/9/9/8k b - 1"

# (c) 手番側(先手)が王手中の盤面(major_piece_drop_threatsの制約と共通)。
TRAPPED_IN_CHECK_SFEN = "4K4/9/4r4/9/9/9/9/9/k8 b r 1"


def test_trapped_major_pieces_detects_cornered_bishop():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    result = analysis.trapped_major_pieces(board)
    entry = next((e for e in result if e["square"] == "3七"), None)
    assert entry is not None
    assert entry["piece"] == "角"


def test_trapped_major_pieces_excludes_piece_with_safe_escape():
    # 同じ盤面の後手飛車(8二)は退避先(5二・6二・7二・9二)に手番側の利きがなく、
    # 安全に逃げられるため対象外。
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    result = analysis.trapped_major_pieces(board)
    assert "8二" not in [e["square"] for e in result]


def test_trapped_major_pieces_empty_while_in_check():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_IN_CHECK_SFEN)
    assert board.is_check()
    assert analysis.trapped_major_pieces(board) == []


def test_trapped_major_pieces_empty_without_opponent_major_piece():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_NO_MAJOR_PIECE_SFEN)
    assert analysis.trapped_major_pieces(board) == []


def test_trapped_major_pieces_includes_promoted_piece():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_PROMOTED_ZERO_MOVES_SFEN)
    result = analysis.trapped_major_pieces(board)
    assert any(e["piece"] == "馬" for e in result)


def test_trapped_major_pieces_excludes_own_side_piece():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_OWN_PROMOTED_NOT_TARGETED_SFEN)
    assert analysis.trapped_major_pieces(board) == []


def test_trapped_major_pieces_reports_zero_legal_moves_for_fully_boxed_piece():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_PROMOTED_ZERO_MOVES_SFEN)
    result = analysis.trapped_major_pieces(board)
    entry = next(e for e in result if e["square"] == "9一")
    assert entry["legal_move_count"] == 0


def test_trapped_major_pieces_does_not_mutate_board():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    before = board.sfen()
    analysis.trapped_major_pieces(board)
    assert board.sfen() == before


def test_analyze_includes_trapped_major_pieces():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    result = analysis.analyze(board)
    assert any(e["square"] == "3七" for e in result["trapped_major_pieces"])


def test_trapped_major_pieces_attackers_zero_when_not_currently_attacked():
    # (f) 追加確認: 既存の§18.3ケースは退避不可だがまだ当たっていない(attackers: 0)。
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    entry = next(e for e in analysis.trapped_major_pieces(board) if e["square"] == "3七")
    assert entry["attackers"] == 0


# TRAPPED_BISHOP_SFENの3九へ先手香を追加し、3七の角に直接利きを足した盤面
# (退避不可かつ既に当たっている状態。attackers >= 1になることの確認用)。
TRAPPED_BISHOP_ATTACKED_SFEN = (
    "ln1g3nl/1r3kgs1/1ppspp1p1/p2p2p2/7Np/2P2PPP1/PPSPPSb1P/2GK5/LN3GLRL b B 28"
)


def test_trapped_major_pieces_attackers_nonzero_when_currently_attacked():
    # (f) 利きを足すと同じ角が引き続き検出されつつattackers >= 1へ切り替わること。
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_ATTACKED_SFEN)
    entry = next(e for e in analysis.trapped_major_pieces(board) if e["square"] == "3七")
    assert entry["attackers"] >= 1


# --- trapped_major_piecesのcolor引数(§20.1, §20.5(c)) ------------------------


def test_trapped_major_pieces_color_defaults_to_side_to_move():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    assert analysis.trapped_major_pieces(board, color=cshogi.BLACK) == (
        analysis.trapped_major_pieces(board)
    )


def test_trapped_major_pieces_color_skips_initial_pass_when_turn_shifted():
    board = cshogi.Board()
    board.set_sfen(TRAPPED_BISHOP_SFEN)
    expected = analysis.trapped_major_pieces(board, color=cshogi.BLACK)

    shifted = cshogi.Board()
    shifted.set_sfen(TRAPPED_BISHOP_SFEN.replace(" b ", " w "))
    assert analysis.trapped_major_pieces(shifted, color=cshogi.BLACK) == expected


# --- major_piece_fork_opportunities(§24.1, §24.5(a)(b)(c)(d)) -----------------


def test_major_piece_fork_opportunities_detects_drop_fork():
    # (a) 2026-07-16対局の36手目相当: 打ち込みで相手の飛・金の2駒に同時に当たり、
    # いずれにも紐が付いていない局面で両取りとして検出されること。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_DROP_SFEN)
    result = analysis.major_piece_fork_opportunities(board)
    entry = next(e for e in result if e["square"] == "5五")
    assert entry["piece"] == "角"
    assert entry["source"] == "drop"
    assert entry["example_move_usi"] == "B*5e"
    assert {t["square"] for t in entry["targets"]} == {"3三", "7七"}


def test_major_piece_fork_opportunities_empty_with_single_target():
    # (b) 当たる駒が1つのみの場合は両取りとして検出されないこと。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_SINGLE_TARGET_SFEN)
    assert analysis.major_piece_fork_opportunities(board) == []


def test_major_piece_fork_opportunities_empty_when_both_targets_defended():
    # (b) 紐が付いている駒しかない場合は検出されないこと。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_BOTH_DEFENDED_SFEN)
    assert analysis.major_piece_fork_opportunities(board) == []


def test_major_piece_fork_opportunities_board_move_excludes_promotion():
    # (c) 盤上の角の移動による両取り: 成り込みゾーン内への移動でも、成る手は
    # 対象外で不成のみが検出されること(major_piece_drop_threatsとの重複回避)。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_BOARD_MOVE_SFEN)
    result = analysis.major_piece_fork_opportunities(board)
    entry = next(e for e in result if e["square"] == "2二")
    assert entry["piece"] == "角"  # 「馬」ではないこと(不成のみ)
    assert entry["source"] == "board"
    assert entry["example_move_usi"] == "9i2b"
    assert {t["square"] for t in entry["targets"]} == {"1三", "3一"}


def test_major_piece_fork_opportunities_excludes_move_that_gives_check():
    # (c) 王手を伴う手は対象外(allows_mate/check_evasionsとの重複回避)。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_GIVES_CHECK_SFEN)
    assert analysis.major_piece_fork_opportunities(board) == []


def test_major_piece_fork_opportunities_empty_while_in_check():
    # (d) 王手中は空リストであること。
    board = cshogi.Board()
    board.set_sfen(IN_CHECK_SFEN.replace(" - ", " B "))
    assert board.is_check()
    assert analysis.major_piece_fork_opportunities(board) == []


def test_major_piece_fork_opportunities_does_not_mutate_board():
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_DROP_SFEN)
    before = board.sfen()
    analysis.major_piece_fork_opportunities(board)
    assert board.sfen() == before


def test_analyze_includes_major_piece_fork_opportunities():
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_DROP_SFEN)
    result = analysis.analyze(board)
    assert any(e["square"] == "5五" for e in result["major_piece_fork_opportunities"])


def test_major_piece_fork_opportunities_real_game_36th_move():
    # (a) games/2026-07-16_074057.kif 36手目相当の実戦再現スモークテスト。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_REAL_GAME_SFEN)
    result = analysis.major_piece_fork_opportunities(board)
    entry = next(e for e in result if e["example_move_usi"] == "B*9e")
    assert entry["piece"] == "角"
    assert entry["source"] == "drop"
    assert {t["square"] for t in entry["targets"]} == {"7三", "8六"}


def test_major_piece_fork_opportunities_include_checks_true_counts_king_as_target():
    # (a)(b) §25.1: include_checks=True かつ王手の場合、玉への当たり(王手)を
    # 1駒分として数え、玉以外の当たりが1つ(7七桂)でも両取りとして採用すること。
    board = cshogi.Board()
    board.set_sfen(OPPONENT_FORK_THREAT_REAL_GAME_SFEN)
    board.push(board.move_from_usi("8i7g"))
    result = analysis.major_piece_fork_opportunities(board, color=cshogi.WHITE, include_checks=True)
    entry = next(e for e in result if e["example_move_usi"] == "B*6f")
    assert entry["piece"] == "角"
    assert entry["source"] == "drop"
    assert {t["square"] for t in entry["targets"]} == {"7七"}


def test_major_piece_fork_opportunities_include_checks_false_still_needs_two_targets():
    # (a) 王手を伴わない手はinclude_checks=Trueでも従来どおり玉以外2駒以上が必要
    # (既存の非王手ケースの回帰確認、include_checksの値によらず不変)。
    board = cshogi.Board()
    board.set_sfen(FORK_OPPORTUNITY_SINGLE_TARGET_SFEN)
    assert analysis.major_piece_fork_opportunities(board, include_checks=True) == []


# --- major_piece_attacked_squares(§25.3) -------------------------------------

# 飛車の走り利き検証用: 先手飛5五が空の盤上に単独。四方への走り利きのみで、
# 隣接1マスの追加利き(飛車にはそもそも存在しない)との混同がないことを確認する。
ATTACKED_SQUARES_ROOK_SFEN = "4k4/9/9/9/4R4/9/9/9/4K4 b - 1"

# 角の走り利き検証用: 先手角5五が空の盤上に単独。斜め4方向の走り利きのみ。
ATTACKED_SQUARES_BISHOP_SFEN = "4k4/9/9/9/4B4/9/9/9/4K4 b - 1"

# 龍の走り利き検証用: 先手龍(成り済み飛車)5五。縦横4方向の走り利きのみを対象とし、
# 隣接8方向への追加の1マス利き(斜め4方向)は対象外であること。
ATTACKED_SQUARES_DRAGON_SFEN = "4k4/9/9/9/4+R4/9/9/9/4K4 b - 1"

# 馬の走り利き検証用: 先手馬(成り済み角)5五。斜め4方向の走り利きのみを対象とし、
# 隣接8方向への追加の1マス利き(縦横4方向)は対象外であること。
ATTACKED_SQUARES_HORSE_SFEN = "4k4/9/9/9/4+B4/9/9/9/4K4 b - 1"

# 遮蔽物検証用: 先手飛5五の上方向2マス先(5三)に後手歩、下方向1マス先(5六)に
# 先手歩を配置。いずれの方向も遮蔽物の升目までを含み、その先は含まないこと。
ATTACKED_SQUARES_BLOCKED_SFEN = "4k4/9/4p4/9/4R4/4P4/9/9/4K4 b - 1"

# color省略時の向き検証用: 手番側(先手)から見て、相手(後手)の角5五の利きを
# 対象とすること(major_piece_drop_threatsと同じ既定の向き、§25.3)。
ATTACKED_SQUARES_DEFAULT_COLOR_SFEN = "4k4/9/9/9/4b4/9/9/9/4K4 b - 1"

# 王手中でも通常どおり計算されることの検証用: 後手飛5gが先手玉5iを直射しつつ、
# 後手角3七も盤上にある(IN_CHECK_SFENを流用し角を追加)。
ATTACKED_SQUARES_IN_CHECK_SFEN = "4k4/9/9/9/9/2b6/4r4/9/4K4 b - 1"


def test_major_piece_attacked_squares_rook_all_four_directions():
    # (e) 飛車の走り利きが四方に正しく列挙されること。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_ROOK_SFEN)
    result = analysis.major_piece_attacked_squares(board, color=cshogi.WHITE)
    squares = {e["square"] for e in result}
    assert squares == {
        "5四", "5三", "5二", "5一", "5六", "5七", "5八", "5九",
        "4五", "3五", "2五", "1五", "6五", "7五", "8五", "9五",
    }
    assert all(e["piece"] == "飛" and e["attacker_square"] == "5五" for e in result)


def test_major_piece_attacked_squares_bishop_all_four_diagonals():
    # (e) 角の走り利きが斜め4方向に正しく列挙されること。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_BISHOP_SFEN)
    result = analysis.major_piece_attacked_squares(board, color=cshogi.WHITE)
    squares = {e["square"] for e in result}
    assert squares == {
        "4四", "3三", "2二", "1一", "4六", "3七", "2八", "1九",
        "6四", "7三", "8二", "9一", "6六", "7七", "8八", "9九",
    }
    assert all(e["piece"] == "角" for e in result)


def test_major_piece_attacked_squares_dragon_excludes_diagonal_single_step():
    # (f) 龍の隣接1マスの斜め利きは対象外で、縦横の走り利きのみ列挙されること。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_DRAGON_SFEN)
    result = analysis.major_piece_attacked_squares(board, color=cshogi.WHITE)
    squares = {e["square"] for e in result}
    assert squares == {
        "5四", "5三", "5二", "5一", "5六", "5七", "5八", "5九",
        "4五", "3五", "2五", "1五", "6五", "7五", "8五", "9五",
    }
    assert "4四" not in squares and "6六" not in squares
    assert all(e["piece"] == "龍" for e in result)


def test_major_piece_attacked_squares_horse_excludes_orthogonal_single_step():
    # (f) 馬の隣接1マスの縦横利きは対象外で、斜めの走り利きのみ列挙されること。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_HORSE_SFEN)
    result = analysis.major_piece_attacked_squares(board, color=cshogi.WHITE)
    squares = {e["square"] for e in result}
    assert squares == {
        "4四", "3三", "2二", "1一", "4六", "3七", "2八", "1九",
        "6四", "7三", "8二", "9一", "6六", "7七", "8八", "9九",
    }
    assert "5四" not in squares and "5六" not in squares
    assert all(e["piece"] == "馬" for e in result)


def test_major_piece_attacked_squares_stops_at_first_blocker_inclusive():
    # (e) 遮蔽物の升目自体は含み、その先の升目は含まないこと(自駒・相手駒とも)。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_BLOCKED_SFEN)
    result = analysis.major_piece_attacked_squares(board, color=cshogi.WHITE)
    squares = {e["square"] for e in result}
    assert "5四" in squares  # 遮蔽物手前の空きマスは含む
    assert "5三" in squares  # 後手歩(遮蔽物)の升目自体は含む
    assert "5二" not in squares and "5一" not in squares  # 遮蔽物より先は含まない
    assert "5六" in squares  # 先手歩(遮蔽物)の升目自体は含む
    assert "5七" not in squares and "5八" not in squares and "5九" not in squares


def test_major_piece_attacked_squares_color_param_defaults_to_side_to_move():
    # (g) colorを省略すると手番側から見た相手の大駒を対象とすること。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_DEFAULT_COLOR_SFEN)
    result = analysis.major_piece_attacked_squares(board)
    assert result  # 手番側(先手)から見て後手角の利きが列挙される
    assert all(e["piece"] == "角" for e in result)


def test_major_piece_attacked_squares_computed_normally_while_in_check():
    # (g) 王手中でも通常どおり計算されること(push_passを使わない静的な走査のため)。
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_IN_CHECK_SFEN)
    assert board.is_check()
    result = analysis.major_piece_attacked_squares(board)
    pieces = {e["piece"] for e in result}
    assert pieces == {"飛", "角"}


def test_major_piece_attacked_squares_does_not_mutate_board():
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_BLOCKED_SFEN)
    before = board.sfen()
    analysis.major_piece_attacked_squares(board)
    assert board.sfen() == before


def test_analyze_includes_major_piece_attacked_squares():
    board = cshogi.Board()
    board.set_sfen(ATTACKED_SQUARES_DEFAULT_COLOR_SFEN)
    result = analysis.analyze(board)
    assert result["major_piece_attacked_squares"]
    assert all(e["piece"] == "角" for e in result["major_piece_attacked_squares"])


# --- simulate_line ----------------------------------------------------------


def test_simulate_line_applies_moves():
    board = cshogi.Board()
    result = analysis.simulate_line(board, ["7g7f", "3c3d", "8h2b+"])
    assert result["applied"] == ["7g7f", "3c3d", "8h2b+"]
    assert result["illegal_move"] is None
    assert result["turn"] == "white"
    # 角交換の途中: 先手は角を取って馬も作った、後手は角を失っただけ
    assert result["material_change"]["black"] == 1000  # 持ち駒角+800, 角→馬+200
    assert result["material_change"]["white"] == -800
    assert "馬" in result["board"]
    assert board.sfen() == cshogi.Board().sfen()  # 元の盤面は不変


def test_simulate_line_reports_illegal_move():
    board = cshogi.Board()
    result = analysis.simulate_line(board, ["7g7f", "7f7e", "3c3d"])
    assert result["applied"] == ["7g7f"]
    assert result["illegal_move"] == {"index": 1, "usi": "7f7e"}
