"""ネイティブの合法手生成(native/shogi_core.c)を、cshogiをオラクルにして検証する(§36.5)。"""

import glob
import random
from pathlib import Path

import cshogi
import pytest
from cshogi import KIF

from shogi_mcp import native_core

pytestmark = pytest.mark.skipif(not native_core.available(), reason="scripts/build_native.sh not run")

SAMPLES = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "samples" / "*.kif")))


def _reference(board: cshogi.Board) -> list[str]:
    return sorted(cshogi.move_to_usi(m) for m in board.legal_moves)


def _assert_same_moves(board: cshogi.Board) -> None:
    sfen = board.sfen()
    assert sorted(native_core.legal_moves(sfen)) == _reference(board), sfen


@pytest.mark.parametrize("depth,expected", [(1, 30), (2, 900), (3, 25_470), (4, 719_731)])
def test_perft_from_start_position(depth, expected):
    # (a)
    assert native_core.perft(cshogi.STARTING_SFEN, depth) == expected


def test_legal_moves_match_cshogi_on_sample_games():
    # (b)
    assert SAMPLES
    checked = 0
    for path in SAMPLES:
        parsed = KIF.Parser.parse_file(path)
        board = cshogi.Board(parsed.sfen)
        for move in parsed.moves:
            _assert_same_moves(board)
            board.push(move)
            checked += 1
    assert checked > 500


def test_legal_moves_match_cshogi_on_random_positions():
    # (c) 持ち駒・成駒・王手・二歩・打ち歩詰め・行き所のない駒の絡む局面を含むランダム対局。
    rng = random.Random(7)
    checked = 0
    for _ in range(60):
        board = cshogi.Board()
        for _ in range(200):
            _assert_same_moves(board)
            checked += 1
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
    assert checked > 5_000


# 後手玉1一は、2一・2二の後手歩で逃げ道がなく、1三の先手金が1二を支える(歩は横に取れない)。▲P*1b は打ち歩詰め。
UCHIFUZUME_SFEN = "7pk/7p1/8G/9/9/9/9/9/K8 b P 1"
NIFU_SFEN = "4k4/9/9/9/9/9/PPPPPPPPP/9/K8 b P 1"

# 打ち歩詰め・二歩・行き所のない駒・成りの強制を直接確認する局面(結果はcshogiと一致を確認)。
SPECIAL_SFENS = [
    UCHIFUZUME_SFEN,  # 1二への歩打ちが打ち歩詰めになる
    NIFU_SFEN,  # 二歩(全筋に自歩)
    "4k4/9/9/9/9/9/9/9/K8 b PLNplnp 1",  # 持ち駒の打てる場所の制限
    "4k4/4P4/9/9/9/9/9/9/K8 b - 1",  # 歩が最奥段へ(成りの強制)
    "4k4/9/4N4/9/9/9/9/9/K8 b - 1",  # 桂が奥2段へ(成りの強制)
    "4k4/9/9/9/9/9/9/4r4/4K4 b - 1",  # 王手放置の禁止
]


@pytest.mark.parametrize("sfen", SPECIAL_SFENS)
def test_legal_moves_match_cshogi_on_special_positions(sfen):
    _assert_same_moves(cshogi.Board(sfen))


def test_apply_moves_matches_cshogi_sfen():
    # (d) 着手後の局面(盤・持ち駒・手番)がcshogiのpush後と一致。手数フィールドは除く。
    rng = random.Random(11)
    for _ in range(20):
        board = cshogi.Board()
        played: list[str] = []
        for _ in range(150):
            moves = list(board.legal_moves)
            if not moves:
                break
            move = rng.choice(moves)
            played.append(cshogi.move_to_usi(move))
            board.push(move)
            native = native_core.apply_moves(cshogi.STARTING_SFEN, played)
            assert native.split()[:3] == board.sfen().split()[:3]


def test_apply_moves_rejects_illegal_move():
    with pytest.raises(ValueError):
        native_core.apply_moves(cshogi.STARTING_SFEN, ["7g7e"])


def test_special_rules_are_actually_exercised():
    # SPECIAL_SFENSが狙いどおりの規則を試していること(cshogiでも同じ結果)。
    assert "P*1b" not in native_core.legal_moves(UCHIFUZUME_SFEN)
    assert not any(m.startswith("P*") for m in native_core.legal_moves(NIFU_SFEN))
    assert "P*1b" not in _reference(cshogi.Board(UCHIFUZUME_SFEN))
    assert "P*1b" in _reference(cshogi.Board(UCHIFUZUME_SFEN.replace("8G", "9")))  # 支えがなければ合法
    assert "P*1b" in native_core.legal_moves(UCHIFUZUME_SFEN.replace("8G", "9"))
