import json
import urllib.error
import urllib.request

import cshogi
import pytest

from shogi_mcp import gui_server, kif_store


@pytest.fixture
def games_dir(tmp_path):
    """コメント・評価値付きの棋譜1つと、コメント無しの棋譜1つを持つgames/相当のディレクトリ。"""
    store = kif_store.KifStore(tmp_path)
    board = cshogi.Board()
    moves = []
    for usi in ["7g7f", "3c3d", "2g2f"]:
        move = board.move_from_usi(usi)
        moves.append(move)
        board.push(move)

    store.start(
        kif_store.GameMeta(difficulty=1, user_side="black", mode="brain"),
        path=tmp_path / "annotated.kif",
    )
    store.save(
        moves,
        resigned=True,
        comments={
            1: ["角道を開ける。"],
            2: ["eval cp:-30 pv:2g2f 8c8d", "自然な応手。"],
            3: ["eval mate:5"],
        },
    )

    store.start(
        kif_store.GameMeta(difficulty=1, user_side="black", mode="auto"),
        path=tmp_path / "plain.kif",
    )
    store.save(moves[:1])
    return tmp_path


@pytest.fixture
def running_server(games_dir):
    server = gui_server.start(lambda: "<svg>dummy</svg>", games_dir=games_dir, port=0)
    assert server is not None
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _get(server, path: str) -> str:
    url = f"http://127.0.0.1:{server.server_port}{path}"
    with urllib.request.urlopen(url, timeout=5) as res:
        return res.read().decode("utf-8")


def test_index_page_contains_polling_script(running_server):
    body = _get(running_server, "/")
    assert "<div id=\"board\">" in body
    assert "/board" in body
    assert "/replay" in body  # リプレイページへのリンク


def test_board_endpoint_returns_fragment(running_server):
    body = _get(running_server, "/board")
    assert body == "<svg>dummy</svg>"


def test_unknown_path_returns_404(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(running_server, "/nope")
    assert exc_info.value.code == 404


def test_start_returns_none_when_port_already_in_use():
    first = gui_server.start(lambda: "", port=0)
    assert first is not None
    try:
        second = gui_server.start(lambda: "", port=first.server_port)
        assert second is None
    finally:
        first.shutdown()
        first.server_close()


# --- リプレイモード -----------------------------------------------------------


def test_replay_page_served(running_server):
    body = _get(running_server, "/replay")
    assert "リプレイ" in body or "振り返り" in body
    assert "/replay/games" in body


def test_replay_games_lists_kif_files(running_server):
    games = json.loads(_get(running_server, "/replay/games"))
    assert set(games) == {"annotated.kif", "plain.kif"}


def test_replay_game_returns_moves_evals_comments(running_server):
    data = json.loads(_get(running_server, "/replay/game?file=annotated.kif"))
    assert data["status"] == "投了"
    moves = data["moves"]
    assert [m["usi"] for m in moves] == ["7g7f", "3c3d", "2g2f"]
    assert [m["ply"] for m in moves] == [1, 2, 3]

    assert moves[0]["eval"] is None
    assert moves[0]["comment"] == "角道を開ける。"

    assert moves[1]["eval"] == {"cp": -30}
    assert moves[1]["eval_pv"] == ["2g2f", "8c8d"]
    assert moves[1]["comment"] == "自然な応手。"

    assert moves[2]["eval"] == {"mate": 5}
    assert moves[2]["eval_pv"] is None
    assert moves[2]["comment"] is None


def test_replay_game_without_comments(running_server):
    data = json.loads(_get(running_server, "/replay/game?file=plain.kif"))
    assert data["status"] is None
    (move,) = data["moves"]
    assert move["eval"] is None and move["comment"] is None


def test_replay_game_returns_player_names(running_server):
    # KIFヘッダーの対局者名がリプレイ用JSONに載ること(02_design.md §13.6)
    data = json.loads(_get(running_server, "/replay/game?file=annotated.kif"))
    assert data["names"] == ["Claude(思考)", "やねうら王 Lv1"]
    data = json.loads(_get(running_server, "/replay/game?file=plain.kif"))
    assert data["names"] == ["Claude(自動)", "やねうら王 Lv1"]


def test_replay_page_shows_players(running_server):
    body = _get(running_server, "/replay")
    assert 'id="players"' in body


def test_replay_board_returns_svg_per_ply(running_server):
    initial = _get(running_server, "/replay/board?file=annotated.kif&ply=0")
    after_two = _get(running_server, "/replay/board?file=annotated.kif&ply=2")
    assert initial.startswith("<svg") or "<svg" in initial
    assert "<svg" in after_two
    assert initial != after_two
    # 範囲外のplyは丸められてエラーにならない
    over = _get(running_server, "/replay/board?file=annotated.kif&ply=99")
    assert "<svg" in over


def test_replay_rejects_missing_and_traversal_paths(running_server):
    for path in (
        "/replay/game?file=missing.kif",
        "/replay/game?file=../secrets.kif",
        "/replay/game?file=..%2Fsecrets.kif",
        "/replay/game",
        "/replay/board?file=../../etc/passwd&ply=0",
    ):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(running_server, path)
        assert exc_info.value.code == 404


def test_replay_board_rejects_non_integer_ply(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(running_server, "/replay/board?file=annotated.kif&ply=abc")
    assert exc_info.value.code == 400
