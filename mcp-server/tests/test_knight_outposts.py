"""桂の居座りの検出(フェーズ42、02_design.md §43)のテスト。"""

import cshogi

from shogi_mcp import analysis

# 2026-10-08の対局(games/2026-10-08_163132.kif)の58手目の直前。後手(Claude)番。
# ▲4五銀に対し、同銀(5d4e)か4三銀引(5d4c)か。同銀は▲同桂で4五に桂が居座る。
BEFORE_EXCHANGE_SFEN = "l5knl/4gs1g1/2n4p1/pr1ps1p+bp/1pp2S3/P2B2P1P/1PN2PNP1/4GGK2/L2R2S1L w 2P3p 58"
# 上の局面で5d4e(同銀)▲3七桂4五(同桂)まで進めた後。後手番。4五に先手の桂が居座っている。
AFTER_LANDING_SFEN = "l5knl/4gs1g1/2n4p1/pr1p2p+bp/1pp2N3/P2B2P1P/1PN2P1P1/4GGK2/L2R2S1L w S2Ps3p 60"


def _names(entries):
    return {e["square"] for e in entries}


def test_established_knight_is_flagged():
    board = cshogi.Board(AFTER_LANDING_SFEN)
    result = analysis.knight_outposts(board, cshogi.WHITE)
    by_square = {e["square"]: e for e in result["on_board"]}
    assert "4五" in by_square
    entry = by_square["4五"]
    assert entry["direct"] is False
    assert {"3三", "5三"} <= set(entry["next"])  # 次の跳躍先が玉(3一)の周囲に利く


def test_knight_that_can_be_captured_is_not_an_outpost():
    # 4四に後手の歩を足す(4五に利く)。取れる桂は居座りではない。
    sfen = AFTER_LANDING_SFEN.replace("pr1p2p+bp", "pr1p1pp+bp")
    board = cshogi.Board(sfen)
    result = analysis.knight_outposts(board, cshogi.WHITE)
    assert "4五" not in _names(result["on_board"])


def test_direct_attack_on_king_zone():
    # 後手玉5一、先手桂4三。桂は3一と5一(玉)に利く(王手)。後手の利きは4三にない。
    board = cshogi.Board("4k4/9/5N3/9/9/9/9/9/4K4 b - 1")
    result = analysis.knight_outposts(board, cshogi.WHITE)
    assert [(e["square"], e["direct"]) for e in result["on_board"]] == [("4三", True)]


def test_color_symmetry():
    # 上の局面を先後反転: 先手玉5九、後手桂6七(7九と5九に利く)。
    board = cshogi.Board("4k4/9/9/9/9/9/3n5/9/4K4 w - 1")
    result = analysis.knight_outposts(board, cshogi.BLACK)
    assert [(e["square"], e["direct"]) for e in result["on_board"]] == [("6七", True)]


def test_promoted_and_own_knights_are_ignored():
    # 成桂は対象外。守り手自身の桂も数えない。
    assert analysis.knight_outposts(cshogi.Board("4k4/9/5+N3/9/9/9/9/9/4K4 b - 1"), cshogi.WHITE) == {
        "on_board": [],
        "drop_squares": [],
    }
    assert analysis.knight_outposts(cshogi.Board("4k4/9/5n3/9/9/9/9/9/4K4 b - 1"), cshogi.WHITE)["on_board"] == []


def test_drop_squares_reach_king_zone_and_exclude_covered_squares():
    # 先手が桂を持つ。後手玉5一。三段目以降で、桂の利き先が玉の周囲に届くマスが打ち込み先。
    board = cshogi.Board("4k4/9/9/9/9/9/9/9/4K4 b N 1")
    squares = set(analysis.knight_outposts(board, cshogi.WHITE)["drop_squares"])
    expected = {f"{f}{r}" for f in "34567" for r in "三四"}
    assert squares == expected
    # 後手の金が5二にあると、金の利く4三・5三・6三は取られるので除かれる。
    board = cshogi.Board("4k4/4g4/9/9/9/9/9/9/4K4 b N 1")
    squares = set(analysis.knight_outposts(board, cshogi.WHITE)["drop_squares"])
    assert squares == expected - {"4三", "5三", "6三"}


def test_no_knight_in_hand_means_no_drop_squares():
    board = cshogi.Board("4k4/9/9/9/9/9/9/9/4K4 b - 1")
    assert analysis.knight_outposts(board, cshogi.WHITE) == {"on_board": [], "drop_squares": []}


def test_analyze_reports_own_and_opponent_knight_outposts():
    result = analysis.analyze(cshogi.Board(AFTER_LANDING_SFEN))
    safety = result["king_safety"]
    assert "4五" in _names(safety["own_knight_outposts"]["on_board"])
    assert set(safety["opponent_knight_outposts"]) == {"on_board", "drop_squares"}


def test_analyze_does_not_mutate_board():
    board = cshogi.Board(AFTER_LANDING_SFEN)
    before = board.sfen()
    analysis.analyze(board)
    assert board.sfen() == before


def test_verify_moves_flags_exchange_that_establishes_the_knight():
    board = cshogi.Board(BEFORE_EXCHANGE_SFEN)
    results = analysis.verify_moves(board, ["5d4e", "5d4c"], depth=3)
    by_usi = {r["usi"]: r for r in results}
    # 同銀は▲同桂で4五に居座られる。4三銀引は交換しないので居座りはない。
    assert "4五" in _names(by_usi["5d4e"]["own_knight_outposts_after_pv"])
    assert by_usi["5d4c"]["own_knight_outposts_after_pv"] == []


def test_verify_moves_outposts_none_when_no_pv():
    # 読み筋が信頼できない(search_depth_completed == 0)ときは他のafter_pvと同じくnull。
    board = cshogi.Board(BEFORE_EXCHANGE_SFEN)
    results = analysis.verify_moves(board, ["5d4e"], depth=3, node_limit=1)
    if results[0]["search_depth_completed"] == 0:
        assert results[0]["own_knight_outposts_after_pv"] is None
