from pathlib import Path

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
