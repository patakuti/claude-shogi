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
        "hanging": True, "cheapest_attacker": "歩", "pawn_drop_risk": False,
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


def test_verify_moves_is_mate_candidate_has_no_destination():
    board = cshogi.Board()
    board.set_sfen(MATE_IN_1_SFEN)
    (entry,) = analysis.verify_moves(board, ["G*5b"])
    assert "destination" not in entry
    assert "own_attacked_after" not in entry


# --- 反復深化がverify_movesの信頼性判断に反映されること(§14.4) -----------------


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
