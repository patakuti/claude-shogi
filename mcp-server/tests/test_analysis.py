import cshogi

from shogi_mcp import analysis

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
    assert not result["mate_threat_skipped_due_to_check"]


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

    board.set_sfen(IN_CHECK_SFEN)
    result = analysis.analyze(board)
    assert result["in_check"]
    assert result["mate_threat_skipped_due_to_check"]


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
