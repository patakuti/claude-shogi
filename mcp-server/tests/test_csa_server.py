"""CSA通信対局プロトコルサーバーの結合テスト(02_design.md §26.10)。

実際のCSA対応クライアントアプリは使わず、テスト専用の最小CSAクライアント(素の
socket)でLOGIN〜対局概要〜指し手交換〜終局通知の一連を自動確認する。
csa_server.pyは_csa_snapshot/_submit_csa_move経由でserver.pyの実セッションと
結線されるため、mode="csa"はUSIエンジンを起動しない(02_design.md §26.6)ことから、
このテストファイルはengine/YaneuraOu-by-gccのビルドを前提としない。
"""

from __future__ import annotations

import socket
import time

import cshogi
import pytest

from shogi_mcp import csa_server, server


@pytest.fixture(autouse=True)
def isolated_games_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "GAMES_DIR", tmp_path)
    yield
    if server._session is not None:
        server._session.close()
        server._session = None


class _CsaTestClient:
    """テスト専用の最小CSAクライアント。"""

    def __init__(self, port: int):
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self._buf = b""

    def close(self) -> None:
        self._sock.close()

    def send(self, text: str) -> None:
        self._sock.sendall((text + "\n").encode("utf-8"))

    def recv_line(self, timeout: float = 5) -> str | None:
        self._sock.settimeout(timeout)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8").strip("\r")

    def recv_until(self, prefix: str, timeout: float = 5) -> str | None:
        """指定した接頭辞で始まる行が来るまで読み進め、その行を返す。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            line = self.recv_line(timeout=remaining)
            if line is None:
                return None
            if line.startswith(prefix):
                return line
        return None


@pytest.fixture
def csa_running_server():
    srv = csa_server.start(server._csa_snapshot, server._submit_csa_move, port=0)
    assert srv is not None
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _login_and_start(client: _CsaTestClient) -> None:
    client.send("LOGIN tester dummy")
    login_reply = client.recv_line()
    assert login_reply is not None and login_reply.startswith("LOGIN:") and "OK" in login_reply
    begin = client.recv_line()
    assert begin == "BEGIN Game_Summary"
    end = client.recv_until("END Game_Summary")
    assert end == "END Game_Summary"
    client.send("AGREE")
    assert client.recv_line() == f"START:{csa_server.GAME_ID}"


def test_login_rejected_when_no_csa_game(csa_running_server):
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        client.send("LOGIN tester dummy")
        assert client.recv_line() == "LOGIN:incorrect"
    finally:
        client.close()


def test_login_rejected_when_mode_is_not_csa(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="brain")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        client.send("LOGIN tester dummy")
        assert client.recv_line() == "LOGIN:incorrect"
    finally:
        client.close()


def test_login_and_game_summary_when_csa_mode(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        client.send("LOGIN tester dummy")
        assert client.recv_line() == "LOGIN:tester OK"
        assert client.recv_line() == "BEGIN Game_Summary"
        end = client.recv_until("END Game_Summary")
        assert end == "END Game_Summary"
    finally:
        client.close()


def test_agree_with_game_id_suffix_is_accepted(csa_running_server):
    """実機(ShogiHome)は"AGREE claude-shogi-csa"のようにGame_IDを付けて返す。"""
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        client.send("LOGIN tester dummy")
        client.recv_line()
        client.recv_line()
        client.recv_until("END Game_Summary")
        client.send("AGREE claude-shogi-csa")
        assert client.recv_line() == f"START:{csa_server.GAME_ID}"
    finally:
        client.close()


def test_reject_ends_without_start(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        client.send("LOGIN tester dummy")
        client.recv_line()
        client.recv_line()
        client.recv_until("END Game_Summary")
        client.send("REJECT")
        # STARTは送られず、接続が閉じる
        assert client.recv_line() is None
    finally:
        client.close()


def test_human_move_is_applied_to_session(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        _login_and_start(client)
        client.send("+7776FU")
        # サーバーは受理した指し手を送信元にもエコーバックする(実クライアント
        # (ShogiHome)が自分の指し手をこの受信経由でしか反映しないため必須)。
        assert client.recv_line() == "+7776FU,T1"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and server._session.game.move_number() == 1:
            time.sleep(0.05)
        assert server._session.game.move_number() == 2
        assert server._session.game.last_move().usi == "7g7f"
    finally:
        client.close()


def test_claude_move_is_relayed_to_client(csa_running_server):
    # user_side=white → 黒番のClaude(対局相手側)が初手を指す
    server.new_game(difficulty=1, user_side="white", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        _login_and_start(client)
        result = server.apply_move("7g7f")
        assert result["ok"]
        line = client.recv_until("+")
        assert line == "+7776FU,T1"
    finally:
        client.close()


def test_human_resign_sends_lose_to_resigning_side(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        _login_and_start(client)
        client.send("%TORYO")
        line = client.recv_until("#")
        assert line == "#LOSE"
    finally:
        client.close()
    assert server._session.resigned is True
    assert server._session.status() == "resigned"


def test_claude_resign_sends_win_to_human(csa_running_server):
    # user_side=white → 黒番のClaude側がresign()を呼んで投了する
    server.new_game(difficulty=1, user_side="white", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        _login_and_start(client)
        result = server.resign()
        assert result["ok"]
        line = client.recv_until("#")
        assert line == "#WIN"
    finally:
        client.close()


def test_winning_move_is_relayed_before_end_signal():
    """詰みを引き起こした指し手は、終局通知(#WIN等)より前に必ずクライアントへ中継される。

    以前は終局判定を手数チェックより先に行っていたため、Claude側の指し手が
    勝敗を決めた場合にその指し手が一度もクライアントへ送られないまま
    #WIN/#LOSEだけが届く不具合があった(実機(ShogiHome)でのプレイ中に発覚)。
    """
    playing_snapshot = csa_server.GameSnapshot(
        mode="csa",
        user_side="black",
        black_name="ユーザー(CSA)",
        white_name="Claude(思考)",
        csa_pos="P1-KY-KE-GI-KI-OU-KI-GI-KE-KY\n+",
        turn="white",
        move_number=1,
        status="playing",
        last_move_csa=None,
    )
    mating_snapshot = csa_server.GameSnapshot(
        mode="csa",
        user_side="black",
        black_name="ユーザー(CSA)",
        white_name="Claude(思考)",
        csa_pos="P1-KY-KE-GI-KI-OU-KI-GI-KE-KY\n+",
        turn="black",
        move_number=2,
        status="checkmate",
        last_move_csa="0068KI",
    )
    snapshots = [playing_snapshot, mating_snapshot, mating_snapshot]

    def get_snapshot():
        return snapshots.pop(0) if snapshots else mating_snapshot

    def submit_move(_raw):
        return {"ok": True}

    srv = csa_server.start(get_snapshot, submit_move, port=0)
    assert srv is not None
    try:
        client = _CsaTestClient(srv.server_port)
        try:
            client.send("LOGIN tester dummy")
            client.recv_line()
            client.recv_line()
            client.recv_until("END Game_Summary")
            client.send("AGREE")
            assert client.recv_line() == f"START:{csa_server.GAME_ID}"
            assert client.recv_line() == "-0068KI,T1"
            assert client.recv_line() == "#LOSE"
        finally:
            client.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_illegal_move_sends_chudan_and_preserves_state(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    client = _CsaTestClient(csa_running_server.server_port)
    try:
        _login_and_start(client)
        client.send("+9999FU")
        line = client.recv_until("#")
        assert line == "#CHUDAN"
    finally:
        client.close()
    assert server._session.status() == "playing"
    assert server._session.game.move_number() == 1


def test_second_connection_rejected_while_one_is_active(csa_running_server):
    server.new_game(difficulty=1, user_side="black", mode="csa")
    first = _CsaTestClient(csa_running_server.server_port)
    second = _CsaTestClient(csa_running_server.server_port)
    try:
        first.send("LOGIN tester1 dummy")
        assert first.recv_line() == "LOGIN:tester1 OK"

        second.send("LOGIN tester2 dummy")
        assert second.recv_line() == "LOGIN:incorrect"
    finally:
        first.close()
        second.close()


# --- CSA表記変換のクロスチェック(打ち込み・成りを含む、02_design.md §26.1) --------


def test_csa_drop_move_round_trips():
    board = cshogi.Board("lnsgkgsnl/1r5b1/pp1ppppp1/9/2p6/9/PPPPPPP1P/1B5R1/LNSGKGSNL b P 4")
    move = board.move_from_csa("0024FU")
    assert move != 0
    assert board.is_legal(move)
    assert cshogi.move_to_usi(move) == "P*2d"
    assert cshogi.move_to_csa(move) == "0024FU"


def test_csa_promotion_move_round_trips():
    board = cshogi.Board()
    for usi in ("7g7f", "3c3d", "8h2b+"):
        board.push(board.move_from_usi(usi))
    csa = cshogi.move_to_csa(board.history[-1])
    assert csa == "8822UM"

    replay = cshogi.Board()
    replay.push_usi("7g7f")
    replay.push_usi("3c3d")
    move = replay.move_from_csa(csa)
    assert cshogi.move_to_usi(move) == "8h2b+"
    assert replay.is_legal(move)
