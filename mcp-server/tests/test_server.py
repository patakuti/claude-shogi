import os
from pathlib import Path
from unittest import mock

import pytest

from shogi_mcp import server

ENGINE_PATH = server.ENGINE_PATH

pytestmark = pytest.mark.skipif(
    not ENGINE_PATH.exists(),
    reason="engine binary not built; run scripts/setup_engine.sh first",
)


@pytest.fixture(autouse=True)
def isolated_games_dir(tmp_path, monkeypatch):
    """gamesディレクトリを一時ディレクトリに差し替え、テスト後にセッションを片付ける。"""
    monkeypatch.setattr(server, "GAMES_DIR", tmp_path)
    yield
    if server._session is not None:
        server._session.close()
        server._session = None


def test_new_game_starts_session_and_autosaves_kif():
    result = server.new_game(difficulty=1, user_side="black")
    assert result["ok"]
    assert result["status"] == "playing"
    assert result["turn"] == "black"
    assert result["move_number"] == 1
    assert len(result["legal_moves"]) == 30
    assert Path(result["kif_path"]).exists()


def test_get_state_without_active_game():
    result = server.get_state()
    assert result == {"ok": False, "error": "no_active_game"}


def test_get_state_reflects_new_game():
    server.new_game(difficulty=1, user_side="black")
    result = server.get_state()
    assert result["ok"]
    assert result["turn"] == "black"


def test_state_and_kif_include_player_names():
    result = server.new_game(difficulty=1, user_side="white", mode="user")
    assert result["players"] == {"black": "やねうら王 Lv1", "white": "ユーザー"}
    # KIFヘッダーにも対局者名が記録されること(02_design.md §13.6)
    text = Path(result["kif_path"]).read_text(encoding="cp932")
    assert "先手：やねうら王 Lv1" in text
    assert "後手：ユーザー" in text
    # GUI盤面フラグメントにも表示されること
    fragment = server._board_fragment()
    assert "▲やねうら王 Lv1 △ユーザー" in fragment


def test_apply_move_updates_state_and_autosaves():
    new_game_result = server.new_game(difficulty=1, user_side="black")
    kif_path = Path(new_game_result["kif_path"])

    result = server.apply_move("7g7f")
    assert result["ok"]
    assert result["turn"] == "white"
    assert result["last_move"]["usi"] == "7g7f"
    assert "７六歩(77)" in kif_path.read_text(encoding="cp932")


def test_apply_move_rejects_illegal_move_with_candidates():
    server.new_game(difficulty=1, user_side="black")
    result = server.apply_move("1a1b")
    assert not result["ok"]
    assert result["error"] == "illegal_move"


def test_engine_move_thinks_and_updates_board():
    server.new_game(difficulty=1, user_side="black")
    server.apply_move("7g7f")

    result = server.engine_move()
    assert result["ok"]
    assert result["turn"] == "black"
    assert result["last_move"] is not None
    assert "think" in result


def test_apply_move_includes_attack_report_for_both_sides():
    server.new_game(difficulty=1, user_side="black")
    result = server.apply_move("7g7f")
    assert "attack_report" in result
    report = result["attack_report"]
    # ▲7六歩で角道が開き、後手(=エンジン側)の3三歩に角の当たりが生じること。
    assert report["user_pieces"] == []
    assert [e["square"] for e in report["engine_pieces"]] == ["3三"]
    assert not report["engine_pieces"][0]["hanging"]


def test_apply_move_attack_report_reflects_user_side_white():
    server.new_game(difficulty=1, user_side="white")
    server.apply_move("2g2f")
    server.apply_move("8c8d")
    server.apply_move("2f2e")
    server.apply_move("8d8e")
    result = server.apply_move("2e2d")

    report = result["attack_report"]
    # user_side="white"なので、白の歩(2三)への当たりはuser_pieces、
    # 黒の歩(2四)への当たりはengine_piecesに載ること。
    assert [e["square"] for e in report["user_pieces"]] == ["2三"]
    assert report["user_pieces"][0]["hanging"]
    assert [e["square"] for e in report["engine_pieces"]] == ["2四"]
    assert not report["engine_pieces"][0]["hanging"]


def test_engine_move_includes_attack_report():
    server.new_game(difficulty=1, user_side="black")
    server.apply_move("7g7f")
    result = server.engine_move()
    assert "attack_report" in result
    assert set(result["attack_report"]) == {"user_pieces", "engine_pieces"}


def test_engine_hint_does_not_modify_board():
    server.new_game(difficulty=1, user_side="black")
    before = server.get_state()

    result = server.engine_hint(multipv=3, byoyomi_ms=1000)
    assert result["ok"]
    assert len(result["candidates"]) >= 2

    after = server.get_state()
    assert before["sfen"] == after["sfen"]


def test_resign_ends_game_and_blocks_further_moves():
    server.new_game(difficulty=1, user_side="black")
    result = server.resign()
    assert result["ok"]
    assert result["status"] == "resigned"

    blocked = server.apply_move("7g7f")
    assert not blocked["ok"]
    assert blocked["error"] == "game_already_over"

    blocked_engine = server.engine_move()
    assert not blocked_engine["ok"]


def test_save_kif_and_load_kif_round_trip(tmp_path):
    server.new_game(difficulty=2, user_side="white", mode="discuss")
    server.apply_move("7g7f")
    server.apply_move("3c3d")

    explicit_path = tmp_path / "saved.kif"
    save_result = server.save_kif(str(explicit_path))
    assert save_result["ok"]
    assert explicit_path.exists()

    server._session.close()
    server._session = None

    load_result = server.load_kif(str(explicit_path))
    assert load_result["ok"]
    assert load_result["difficulty"] == 2
    assert load_result["user_side"] == "white"
    assert load_result["mode"] == "discuss"
    assert load_result["move_number"] == 3
    assert load_result["turn"] == "black"


def test_load_kif_accepts_relative_path_that_already_includes_directory():
    # 実際にls -t games/*.kifで自動保存先を探すと、GAMES_DIRのプレフィックスを
    # 含んだ相対パス(例: "games/xxx.kif")が返る。これをそのままGAMES_DIRへ
    # 連結すると"games/games/xxx.kif"のような二重パスになってしまう不具合があった。
    result = server.new_game(difficulty=1, user_side="black")
    kif_path = Path(result["kif_path"])
    server._session.close()
    server._session = None

    relative = os.path.relpath(kif_path, Path.cwd())
    load_result = server.load_kif(relative)
    assert load_result["ok"], load_result


def test_analysis_tools_require_active_game():
    assert server.analyze_position() == {"ok": False, "error": "no_active_game"}
    assert server.verify_moves(["7g7f"]) == {"ok": False, "error": "no_active_game"}
    assert server.simulate_line(["7g7f"]) == {"ok": False, "error": "no_active_game"}


def test_new_game_accepts_brain_mode():
    result = server.new_game(difficulty=1, user_side="black", mode="brain")
    assert result["ok"]
    assert result["mode"] == "brain"


def test_analyze_position_returns_summary_without_moving():
    server.new_game(difficulty=1, user_side="black", mode="brain")
    before = server.get_state()["sfen"]

    result = server.analyze_position()
    assert result["ok"]
    assert result["material"]["diff_black_minus_white"] == 0
    assert result["mate_for_side_to_move"] is None

    assert server.get_state()["sfen"] == before


def test_verify_moves_checks_candidates_without_moving():
    server.new_game(difficulty=1, user_side="black", mode="brain")
    before = server.get_state()["sfen"]

    result = server.verify_moves(["7g7f", "1a1b"])
    assert result["ok"]
    ok_entry, bad_entry = result["results"]
    assert ok_entry["legal"]
    assert ok_entry["allows_mate"] is None
    assert not bad_entry["legal"]

    assert server.get_state()["sfen"] == before


def test_verify_moves_clamps_node_limit_to_safe_range():
    server.new_game(difficulty=1, user_side="black", mode="brain")
    captured = {}
    original = server.analysis.verify_moves

    def spy(board, moves, depth, node_limit):
        captured["node_limit"] = node_limit
        return original(board, moves, depth=depth, node_limit=node_limit)

    with mock.patch.object(server.analysis, "verify_moves", side_effect=spy):
        server.verify_moves(["7g7f"], node_limit=1)
        assert captured["node_limit"] == 1_000
        server.verify_moves(["7g7f"], node_limit=10_000_000)
        assert captured["node_limit"] == 300_000
        server.verify_moves(["7g7f"], node_limit=50_000)
        assert captured["node_limit"] == 50_000


def test_simulate_line_does_not_touch_real_board():
    server.new_game(difficulty=1, user_side="black", mode="brain")
    before = server.get_state()["sfen"]

    result = server.simulate_line(["7g7f", "3c3d", "8h2b+"])
    assert result["ok"]
    assert result["applied"] == ["7g7f", "3c3d", "8h2b+"]
    assert result["illegal_move"] is None

    assert server.get_state()["sfen"] == before
    assert server.get_state()["move_number"] == 1


def test_apply_move_comment_is_saved_to_kif():
    result = server.new_game(difficulty=1, user_side="black", mode="brain")
    kif_path = Path(result["kif_path"])

    server.apply_move("7g7f", comment="角道を開ける。")
    loaded = server.kif_store.KifStore.load(kif_path)
    assert loaded.comments == {1: ["角道を開ける。"]}


def test_engine_move_records_normalized_eval_comment():
    result = server.new_game(difficulty=1, user_side="black")
    kif_path = Path(result["kif_path"])
    server.apply_move("7g7f")

    move_result = server.engine_move()
    assert move_result["ok"]

    loaded = server.kif_store.KifStore.load(kif_path)
    # 2手目(後手=エンジンの手)に評価値行が付いていること
    assert 2 in loaded.comments
    eval_line = loaded.comments[2][0]
    assert eval_line.startswith("eval ")
    assert ("cp:" in eval_line) or ("mate:" in eval_line)

    # 符号の正規化: 後手が指した直後の評価値なので、エンジン(手番側)視点の値を
    # 符号反転した「先手有利=正」の値が書かれている
    think = move_result["think"]
    if think["score_cp"] is not None:
        assert f"cp:{-think['score_cp']}" in eval_line


def test_add_comment_appends_to_last_move():
    result = server.new_game(difficulty=1, user_side="black")
    kif_path = Path(result["kif_path"])

    blocked = server.add_comment("まだ指していない")
    assert not blocked["ok"]
    assert blocked["error"] == "no_move_to_comment"

    server.apply_move("7g7f", comment="角道を開ける。")
    ok = server.add_comment("後から一言。")
    assert ok["ok"]
    assert ok["move_number"] == 1

    loaded = server.kif_store.KifStore.load(kif_path)
    assert loaded.comments == {1: ["角道を開ける。", "後から一言。"]}


def test_add_comment_works_after_game_over():
    server.new_game(difficulty=1, user_side="black")
    server.apply_move("7g7f")
    server.resign()

    result = server.add_comment("完敗。次はもっと粘る。")
    assert result["ok"]
    assert result["move_number"] == 1


def test_load_kif_restores_comments_and_autosave_keeps_them():
    result = server.new_game(difficulty=1, user_side="black", mode="brain")
    kif_path = Path(result["kif_path"])
    server.apply_move("7g7f", comment="角道を開ける。")

    server._session.close()
    server._session = None

    load_result = server.load_kif(str(kif_path))
    assert load_result["ok"]

    # 再開後に指し進めて自動保存(全体書き直し)されても、既存コメントが残ること
    server.apply_move("3c3d")
    server.apply_move("2g2f", comment="飛車先を伸ばす。")
    loaded = server.kif_store.KifStore.load(kif_path)
    assert loaded.comments == {1: ["角道を開ける。"], 3: ["飛車先を伸ばす。"]}


def test_board_fragment_without_active_game():
    from shogi_mcp import gui_server

    assert server._board_fragment() == gui_server.NO_GAME_FRAGMENT


def test_board_fragment_reflects_current_state():
    server.new_game(difficulty=1, user_side="black")
    fragment = server._board_fragment()
    assert "<svg" in fragment
    assert "手数=" not in fragment  # 初期局面はまだ着手なし

    server.apply_move("7g7f")
    fragment_after = server._board_fragment()
    assert "手数=1" in fragment_after


def test_load_kif_restores_resigned_game(tmp_path):
    server.new_game(difficulty=1, user_side="black")
    server.apply_move("7g7f")
    server.resign()
    kif_path = server._session.kif_store.path

    server._session.close()
    server._session = None

    load_result = server.load_kif(str(kif_path))
    assert load_result["ok"]
    assert load_result["status"] == "resigned"

    blocked = server.apply_move("3c3d")
    assert not blocked["ok"]
