import time
from pathlib import Path

import pytest

from shogi_mcp.usi_engine import UsiEngine, UsiEngineError, UsiTimeoutError

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = REPO_ROOT / "engine" / "YaneuraOu-by-gcc"

pytestmark = pytest.mark.skipif(
    not ENGINE_PATH.exists(),
    reason="engine binary not built; run scripts/setup_engine.sh first",
)

STARTING_SFEN = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"


@pytest.fixture
def engine():
    eng = UsiEngine(str(ENGINE_PATH), options={"USI_OwnBook": False, "Threads": 1})
    eng.start()
    yield eng
    eng.quit()


def test_start_and_quit_lifecycle():
    eng = UsiEngine(str(ENGINE_PATH), options={"USI_OwnBook": False})
    assert not eng.is_alive()
    eng.start()
    assert eng.is_alive()
    eng.quit()
    assert not eng.is_alive()


def test_go_returns_bestmove(engine):
    result = engine.go(sfen=STARTING_SFEN, moves=[], byoyomi_ms=1000)
    assert result.bestmove
    assert result.bestmove != "resign"


def test_go_respects_nodes_limit():
    # NodesLimitで実際に探索が打ち切られることを確認する
    # (フェーズ1でNodesLimitが機能することを実測済み。ここではusi_engine.py側の
    # setoption送信・info行パースが正しく機能することを検証する)。
    eng = UsiEngine(str(ENGINE_PATH), options={"USI_OwnBook": False})
    eng.start()
    try:
        eng.set_option("NodesLimit", 1000)
        result = eng.go(sfen=STARTING_SFEN, moves=[], byoyomi_ms=5000)
        assert result.bestmove
        assert result.primary is not None
        assert result.primary.nodes is not None
        assert result.primary.nodes < 5000
    finally:
        eng.quit()


def test_go_with_moves_updates_position(engine):
    result = engine.go(sfen=STARTING_SFEN, moves=["7g7f"], byoyomi_ms=1000)
    assert result.bestmove


def test_multipv_returns_multiple_candidates():
    eng = UsiEngine(str(ENGINE_PATH), options={"USI_OwnBook": False})
    eng.start()
    try:
        eng.set_option("MultiPV", 3)
        result = eng.go(sfen=STARTING_SFEN, moves=[], byoyomi_ms=1500)
        assert len(result.pvs) >= 2
        assert 1 in result.pvs
    finally:
        eng.quit()


def test_go_raises_when_process_not_started():
    eng = UsiEngine(str(ENGINE_PATH))
    with pytest.raises(UsiEngineError):
        eng.go(sfen=STARTING_SFEN, moves=[], byoyomi_ms=1000)


def test_restart_after_crash():
    eng = UsiEngine(str(ENGINE_PATH), options={"USI_OwnBook": False})
    eng.start()
    eng._proc.kill()  # 異常終了を模擬する(ホワイトボックステスト)
    eng._proc.wait()
    assert not eng.is_alive()

    eng.restart()
    assert eng.is_alive()
    result = eng.go(sfen=STARTING_SFEN, moves=[], byoyomi_ms=1000)
    assert result.bestmove
    eng.quit()


def test_wait_for_raises_timeout_when_deadline_already_passed():
    eng = UsiEngine(str(ENGINE_PATH))
    with pytest.raises(UsiTimeoutError):
        eng._wait_for("readyok", deadline=time.monotonic() - 1)
