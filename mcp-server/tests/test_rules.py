import cshogi

from shogi_mcp.rules import STATUS_CHECKMATE, STATUS_DRAW_REPETITION, STATUS_NYUGYOKU, STATUS_PLAYING, Game

# 打ち歩詰め局面: 後手玉が1a、香で2a/2bを塞ぎ、桂で1bを利かせている。
# 先手が歩を1bに打つと詰みになってしまうため、打ち歩詰めルールにより非合法となる。
UCHIFUZUME_SFEN = "7lk/7l1/9/7N1/9/9/9/9/4K4 b P 1"

# 二歩局面: 先手の7筋の歩を手駒に見立てた局面(5筋には歩が残っている)。
NIFU_SFEN = "lnsgkgsnl/1r5b1/pppppp1pp/9/9/9/PP1PPPPPP/1B5R1/LNSGKGSNL b P 1"

# 詰み局面: 後手玉が1a、香で2a/2bを塞ぎ、飛車が1筋に利いている。後手番で合法手なし。
CHECKMATE_SFEN = "7lk/7l1/8R/9/9/9/9/9/4K4 w - 1"

# 入玉宣言勝ち局面: 先手玉が敵陣(5a)に入り、飛車4・角4・金2(計10枚, 42点)が敵陣内。
NYUGYOKU_SFEN = "RB2K2BR/RB2G2BR/4G4/9/9/9/9/9/4k4 b - 1"

# 千日手: 両王だけの局面で同一手順を繰り返す。
SENNICHITE_SFEN = "9/9/9/9/4k4/9/9/9/4K4 b - 1"


def test_initial_position_has_30_legal_moves():
    game = Game()
    assert len(game.legal_moves()) == 30
    assert game.turn() == "black"
    assert game.move_number() == 1
    assert game.status() == STATUS_PLAYING


def test_legal_moves_include_usi_and_kif_notation():
    game = Game()
    moves = {m.usi: m.kif for m in game.legal_moves()}
    assert moves["7g7f"] == "７六歩(77)"


def test_apply_move_updates_state():
    game = Game()
    result = game.apply_move("7g7f")
    assert result.ok
    assert result.error is None
    assert game.turn() == "white"
    assert game.move_number() == 2
    assert game.last_move().usi == "7g7f"


def test_apply_move_rejects_illegal_move_with_candidates():
    game = Game()
    result = game.apply_move("1a1b")
    assert not result.ok
    assert result.error == "illegal_move"


def test_apply_move_rejects_nifu():
    game = Game(sfen=NIFU_SFEN)
    result = game.apply_move("P*5e")
    assert not result.ok
    assert result.error == "illegal_move"
    # 空いている7筋への打ちは合法
    ok_result = game.apply_move("P*7e")
    assert ok_result.ok


def test_apply_move_rejects_uchifuzume():
    game = Game(sfen=UCHIFUZUME_SFEN)
    result = game.apply_move("P*1b")
    assert not result.ok
    assert result.error == "illegal_move"


def test_checkmate_status():
    game = Game(sfen=CHECKMATE_SFEN)
    assert game.status() == STATUS_CHECKMATE
    assert game.is_game_over()
    assert game.legal_moves() == []


def test_nyugyoku_status():
    game = Game(sfen=NYUGYOKU_SFEN)
    assert game.status() == STATUS_NYUGYOKU
    assert game.is_game_over()


def test_sennichite_status():
    game = Game(sfen=SENNICHITE_SFEN)
    for usi in ["5i4i", "5e4e", "4i5i", "4e5e"]:
        result = game.apply_move(usi)
        assert result.ok
    assert game.status() == STATUS_DRAW_REPETITION
    assert game.is_game_over()


def test_board_display_contains_header_and_last_move():
    game = Game()
    game.apply_move("7g7f")
    display = game.board_display()
    assert "９ ８ ７ ６ ５ ４ ３ ２ １" in display
    assert "手数=1  ▲７六歩(77) まで" in display


def test_board_display_with_no_moves_has_no_trailer():
    game = Game()
    display = game.board_display()
    assert "手数=" not in display


def test_last_move_line_matches_board_display_trailer():
    game = Game()
    assert game.last_move_line() is None
    game.apply_move("7g7f")
    assert game.last_move_line() == "手数=1  ▲７六歩(77) まで"


def test_board_svg_initial_position_has_no_lastmove_highlight():
    game = Game()
    svg = game.board_svg()
    assert svg.startswith("<svg")
    assert "black-pawn" in svg
    assert "white-pawn" in svg
    assert "#f6b94d" not in svg  # 直前手ハイライトは未着手なので出ない


def test_board_svg_changes_after_move_and_highlights_lastmove():
    game = Game()
    before = game.board_svg()
    game.apply_move("7g7f")
    after = game.board_svg()
    assert after != before
    assert "#f6b94d" in after  # 直前手のマスがハイライトされる
