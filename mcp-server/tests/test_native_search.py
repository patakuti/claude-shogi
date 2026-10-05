"""ネイティブ探索(native/shogi_search.c)をPython版の`_Searcher`と比較して検証する(§37.2)。"""

import glob
import random
from pathlib import Path

import cshogi
import pytest
from cshogi import KIF

from shogi_mcp import analysis, native_search

pytestmark = pytest.mark.skipif(analysis._native_search is None, reason="scripts/build_native.sh not run")

SAMPLES = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "samples" / "*.kif")))
FREE_CAPTURE_SFEN = "8k/9/9/9/4g4/9/9/4R4/K8 b - 1"
HUGE = 10**9


def _disable_python_pruning(monkeypatch):
    monkeypatch.setattr(analysis, "_NULL_MOVE_MIN_DEPTH", 99)
    monkeypatch.setattr(analysis, "_LMR_MIN_DEPTH", 99)
    monkeypatch.setattr(analysis, "_FUTILITY_MARGIN", HUGE)
    monkeypatch.setattr(analysis, "_DELTA_MARGIN", HUGE)
    monkeypatch.setattr(analysis, "_TT_CUTOFFS", False)
    monkeypatch.setattr(analysis, "_QUIESCE_PRUNING", False)


def _native(board, depth, flags=0, node_limit=10_000_000):
    searcher = analysis._native_search.searcher(
        cshogi.Board(board.sfen()), node_limit, analysis._native_search.new_context(), flags
    )
    score, pv = searcher.search(depth, -analysis.MATE_SCORE - 1, analysis.MATE_SCORE + 1)
    return searcher, score, pv


def _python(board, depth, node_limit=10_000_000):
    searcher = analysis._Searcher(cshogi.Board(board.sfen()), node_limit)
    score, pv = searcher.search(depth, -analysis.MATE_SCORE - 1, analysis.MATE_SCORE + 1)
    return searcher, score, pv


def _positions(count: int):
    """実戦棋譜とランダム対局から局面を集める(終局局面は除く)。"""
    rng = random.Random(21)
    out = []
    for path in SAMPLES[:4]:
        parsed = KIF.Parser.parse_file(path)
        board = cshogi.Board(parsed.sfen)
        for i, move in enumerate(parsed.moves):
            if i % 7 == 0 and not board.is_game_over():
                out.append(cshogi.Board(board.sfen()))
            board.push(move)
    while len(out) < count:
        board = cshogi.Board()
        for _ in range(rng.randint(20, 120)):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
        if not board.is_game_over():
            out.append(board)
    return out[:count]


def test_scores_match_python_when_pruning_is_disabled(monkeypatch):
    # 枝刈り・TT打ち切りなしの探索値は手順序に依存しない最小最大値なので、一致する。
    _disable_python_pruning(monkeypatch)
    for board in _positions(40):
        for depth in (1, 2):
            _, native_score, _ = _native(board, depth, native_search.NO_PRUNING)
            _, python_score, _ = _python(board, depth)
            assert native_score == python_score, (board.sfen(), depth)


def test_native_pv_is_legal_and_starts_with_best_move():
    board = cshogi.Board(FREE_CAPTURE_SFEN)
    _, score, pv = _native(board, 2)
    assert cshogi.move_to_usi(pv[0]) == "5h5e"
    assert score > 400
    replay = cshogi.Board(FREE_CAPTURE_SFEN)
    for move in pv:
        assert move in list(replay.legal_moves)
        replay.push(move)


def test_native_search_respects_node_limit():
    board = cshogi.Board(SAMPLES and cshogi.STARTING_SFEN)
    searcher, _, _ = _native(board, 6, node_limit=500)
    assert searcher.truncated
    assert searcher.nodes <= 500 + 100


def test_native_matches_python_on_tactical_results(monkeypatch):
    # 枝刈りありでも、取れる駒を取る・詰みを見つける局面で同じ最善手を返す。
    board = cshogi.Board(FREE_CAPTURE_SFEN)
    assert cshogi.move_to_usi(_native(board, 3)[2][0]) == cshogi.move_to_usi(_python(board, 3)[2][0])
    mate = cshogi.Board("4k4/9/4P4/9/9/9/9/9/4K4 b G 1")  # 頭金で詰み
    _, score, pv = _native(mate, 1)
    assert cshogi.move_to_usi(pv[0]) == "G*5b"


def test_search_result_format_with_native():
    result = analysis.search_material(cshogi.Board(cshogi.STARTING_SFEN), depth=2)
    assert set(result) == {"score", "pv_usi", "nodes", "truncated", "completed_depth"}
    assert result["completed_depth"] == 2 and result["truncated"] is False


def test_shared_context_is_deterministic():
    tables_a, tables_b = analysis._SearchTables(), analysis._SearchTables()
    board = cshogi.Board(FREE_CAPTURE_SFEN)
    results = []
    for tables in (tables_a, tables_b):
        searcher = analysis._make_searcher(cshogi.Board(board.sfen()), 100_000, tables)
        results.append(analysis._iterative_deepen(searcher, 3))
    assert results[0] == results[1]
