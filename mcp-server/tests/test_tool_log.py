"""思考用ツール呼び出しのJSONLログ(§39)のテスト。"""

import inspect
import json
from pathlib import Path

import pytest

from shogi_mcp import server, tool_log

pytestmark = pytest.mark.skipif(
    not server.ENGINE_PATH.exists(),
    reason="engine binary not built; run scripts/setup_engine.sh first",
)


@pytest.fixture(autouse=True)
def isolated_games_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "GAMES_DIR", tmp_path)
    monkeypatch.delenv("SHOGI_MCP_TOOLLOG", raising=False)
    yield
    if server._session is not None:
        server._session.close()
        server._session = None


def _entries(kif_path: str) -> list[dict]:
    path = tool_log.log_path(Path(kif_path))
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _new_game() -> str:
    return server.new_game(difficulty=1, user_side="black", mode="brain")["kif_path"]


def test_logged_tools_append_one_line_each():
    # (a)
    kif_path = _new_game()
    server.rank_moves(depth=1)
    server.verify_moves(["7g7f", "2g2f"])
    server.analyze_position()
    server.simulate_line(["7g7f", "3c3d"])
    server.apply_move("7g7f", comment="角道を開ける" * 50)
    entries = _entries(kif_path)
    assert [e["tool"] for e in entries] == [
        "rank_moves", "verify_moves", "analyze_position", "simulate_line", "apply_move",
    ]
    for e in entries:
        assert set(e) == {"ts", "tool", "ply", "elapsed_ms", "args", "summary"}
        assert e["elapsed_ms"] >= 0
    assert [e["ply"] for e in entries] == [0, 0, 0, 0, 0]
    assert len(entries[-1]["args"]["comment"]) == 200  # 長い文字列は切る
    assert entries[-1]["args"]["move"] == "7g7f"


def test_rank_moves_summary_has_depth_and_time_limit_and_result_is_unchanged():
    # (b)
    kif_path = _new_game()
    result = server.rank_moves(depth=2, time_limit=60)
    summary = _entries(kif_path)[0]["summary"]
    assert summary["depth"] == result["depth"] == 2
    assert summary["depth_requested"] == 2 and summary["time_limited"] is False
    assert summary["legal_count"] == 30 and len(summary["top"]) == 3
    assert set(summary["top"][0]) == {"usi", "score", "material_change"}
    assert _entries(kif_path)[0]["args"]["time_limit"] == 60  # 引数は実効値(既定を含む)


def test_verify_moves_summary_lists_depth_per_candidate():
    kif_path = _new_game()
    server.verify_moves(["7g7f", "2g2f"])
    results = _entries(kif_path)[0]["summary"]["results"]
    assert [r["usi"] for r in results] == ["7g7f", "2g2f"]
    assert all("search_depth_completed" in r and "search_truncated" in r for r in results)


def test_ply_follows_the_game():
    kif_path = _new_game()
    server.apply_move("7g7f")
    server.rank_moves(depth=1)
    assert [e["ply"] for e in _entries(kif_path)] == [0, 1]


def test_logging_can_be_disabled_by_env(monkeypatch):
    # (c)
    monkeypatch.setenv("SHOGI_MCP_TOOLLOG", "0")
    kif_path = _new_game()
    server.rank_moves(depth=1)
    assert _entries(kif_path) == []


def test_log_failure_does_not_affect_tool_result(monkeypatch, capsys):
    # (d)
    kif_path = _new_game()

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tool_log, "record", broken)
    result = server.rank_moves(depth=1)
    assert result["ok"] and result["legal_count"] == 30
    assert "[tool_log] failed to log rank_moves" in capsys.readouterr().err
    assert _entries(kif_path) == []


def test_no_active_game_is_not_logged_and_does_not_fail():
    assert server.rank_moves() == {"ok": False, "error": "no_active_game"}


def test_tool_signatures_are_preserved():
    # (e) FastMCPが引数スキーマを作るため、デコレータで引数が変わらないこと。
    assert list(inspect.signature(server.rank_moves).parameters) == ["top_n", "depth", "time_limit", "exact_n"]
    assert list(inspect.signature(server.apply_move).parameters) == [
        "move", "comment", "include_board", "include_legal_moves",
    ]
    assert list(inspect.signature(server.verify_moves).parameters) == [
        "moves", "depth", "node_limit", "mate_ply",
    ]
