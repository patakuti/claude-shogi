"""127.0.0.1:4081でCSA通信対局プロトコル(サブセット)を提供するTCPサーバー。

CSA対局モード(mode="csa")専用: ユーザー側はCSA対応クライアント(ShogiGUI等、
Wine経由・同一マシン)から接続して実際に指し、対局相手側はClaudeが思考モードと
同じロジックで指す(02_design.md §26)。標準ライブラリのsocket/socketserver/
threadingのみに依存する(gui_server.pyと同じ、新規の外部依存を追加しない方針)。

このモジュールはSessionState/rules.Gameの内部に直接依存しない。server.pyが
GameSnapshot(状態のスナップショット)を組み立てる関数と、指し手を反映する
関数の2つをコールバックとして渡す(gui_serverのboard_fragmentコールバックと
同じ設計パターン)。
"""

from __future__ import annotations

import socket
import socketserver
import threading
from dataclasses import dataclass
from typing import Callable, Optional

PORT = 4081

# CSA対局のGame_ID。Game_Summaryで通知し、START応答にも同じ値を含める
# (下記の通り、実クライアントは"START:<Game_ID>"の形式を要求する)。
GAME_ID = "claude-shogi-csa"

# Claude側の着手が反映されるのを待つときのポーリング間隔(秒)。02_design.md §26.4。
_POLL_INTERVAL = 0.2

_STATUS_PLAYING = "playing"


@dataclass(frozen=True)
class GameSnapshot:
    """csa_server.pyがserver.pyから受け取る対局状態のスナップショット(02_design.md §26.2)。"""

    mode: str
    user_side: str  # "black" | "white": CSAクライアント側(人間)が担当する手番
    black_name: str
    white_name: str
    csa_pos: str  # 現局面のCSA形式(Game_Summaryの BEGIN Position に使う)
    turn: str  # "black" | "white": 現在の手番
    move_number: int
    status: str  # rules.STATUS_*文字列、または"resigned"
    last_move_csa: Optional[str]  # 直前の指し手(符号なしCSA表記)。1手も無ければNone


# 符号なしCSA表記の指し手、または投了を示す"%TORYO"を受け取り、反映結果を返す。
# 戻り値は{"ok": True, ...}または{"ok": False, "error": ...}(server.py側で実装)。
GetSnapshot = Callable[[], Optional[GameSnapshot]]
SubmitMove = Callable[[str], dict]


def _winner_side(status: str, mover: str) -> Optional[str]:
    """終局理由(status)と終局検出時点の手番(mover)から勝者側を返す(引き分け/対局中はNone)。

    resigned/checkmate: 手番側(mover)が負け(投了は自分の手番で行う。詰みは
    手番側に合法手が無い状態)。nyugyoku: 手番側(mover)が勝ち(入玉宣言は宣言条件を
    満たした手番側が行う。mcp-server/tests/test_rules.pyのtest_nyugyoku_status
    ——黒番のときに黒が宣言条件を満たすSFEN——で実機確認済み)。
    """
    if status in ("resigned", "checkmate"):
        return "white" if mover == "black" else "black"
    if status == "nyugyoku":
        return mover
    return None


def _csa_line(text: str) -> bytes:
    # 対局者名に日本語(「ユーザー(CSA)」「Claude(思考)」等)を含むためUTF-8で送る。
    # 実際の対応クライアントとの文字コード互換性は手動スモークテストで確認する
    # (02_design.md §26.10)。
    return (text + "\n").encode("utf-8")


class _ConnectionHandler:
    """CSA接続1本分のプロトコル処理(LOGIN〜対局概要〜指し手交換〜終局通知)。"""

    def __init__(self, conn: socket.socket, get_snapshot: GetSnapshot, submit_move: SubmitMove):
        self._conn = conn
        self._get_snapshot = get_snapshot
        self._submit_move = submit_move
        self._buf = b""

    def run(self) -> None:
        try:
            self._handle()
        except (OSError, ConnectionError):
            pass
        finally:
            try:
                self._conn.close()
            except OSError:
                pass

    def _send(self, text: str) -> None:
        self._conn.sendall(_csa_line(text))

    def _recv_line(self) -> Optional[str]:
        """次の1行をブロッキング受信する。接続が閉じられたらNoneを返す。"""
        while b"\n" not in self._buf:
            chunk = self._conn.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip("\r")

    def _handle(self) -> None:
        login = self._recv_line()
        if login is None or not login.startswith("LOGIN "):
            return
        parts = login.split()
        username = parts[1] if len(parts) > 1 else "user"

        snapshot = self._get_snapshot()
        if snapshot is None or snapshot.mode != "csa":
            # 対局セッションがcsaモードでない(=CSA対局モードの対局が開始されていない)。
            self._send("LOGIN:incorrect")
            return
        self._send(f"LOGIN:{username} OK")

        self._send_game_summary(snapshot)

        reply = self._recv_line()
        # クライアントはGame_IDを付けて返すことがある(例: "AGREE claude-shogi-csa"、
        # 実クライアント(ShogiHome)で実機確認済み)。先頭一致で判定する。
        if reply is None or not reply.startswith("AGREE"):
            return
        # 素の"START"だけでは実クライアント(ShogiHome)が対局開始を認識しない
        # (`command.startsWith("START:")`でしか判定していない。ShogiHome
        # src/background/csa/client.tsをGitHub上で実機確認)。CSAプロトコル仕様どおり
        # "START:<Game_ID>"の形式で送る。
        self._send(f"START:{GAME_ID}")

        self._play(snapshot)

    def _send_game_summary(self, snapshot: GameSnapshot) -> None:
        # 持ち時間はClaude側の思考時間(数秒〜数十秒)を見込み、クライアント側の
        # 時間切れ判定で対局が打ち切られないよう余裕を持った値にしている
        # (時間切れの検出・強制自体は本サーバー側では行わない、02_design.md §26.3)。
        # 実際の値の妥当性は手動スモークテストで確認する。
        lines = [
            "BEGIN Game_Summary",
            "Protocol_Version:1.1",
            "Protocol_Mode:Server",
            "Format:Shogi 1.0",
            "Declaration:Jishogi 1.1",
            f"Game_ID:{GAME_ID}",
            f"Name+:{snapshot.black_name}",
            f"Name-:{snapshot.white_name}",
            f"Your_Turn:{'+' if snapshot.user_side == 'black' else '-'}",
            "Rematch_On_Draw:NO",
            f"To_Move:{'+' if snapshot.turn == 'black' else '-'}",
            "BEGIN Time",
            "Time_Unit:1sec",
            "Least_Time_Per_Move:1",
            "Total_Time:1500",
            "Byoyomi:60",
            "END Time",
            "BEGIN Position",
            snapshot.csa_pos,
            "END Position",
            "END Game_Summary",
        ]
        for line in lines:
            self._send(line)

    def _play(self, snapshot: GameSnapshot) -> None:
        last_move_number = snapshot.move_number
        while True:
            snapshot = self._get_snapshot()
            if snapshot is None:
                return
            if snapshot.move_number != last_move_number:
                # 前回確認時から指し手が反映されている。手番はすでに反転済みのため、
                # 直前の着手者は「現在の手番の反対側」。詰みを引き起こした指し手も
                # ここで必ず中継してからでないと終局通知(#WIN等)を送らない
                # (先に終局判定してしまうと、勝敗を決めた最後の指し手がクライアントへ
                # 一度も届かないまま試合が終わってしまう不具合があった。実機確認)。
                mover = "white" if snapshot.turn == "black" else "black"
                if mover != snapshot.user_side and snapshot.last_move_csa:
                    # Claude側(人間側以外)の着手 → クライアントへ通知する。
                    # 人間側自身の着手はクライアントが既に把握しているため送り返さない。
                    # 経過時間(",T<秒>")はCSAプロトコル上必須の書式であり、無いと
                    # 実クライアント(ShogiHome)がパースエラーをログに出す(実機確認)。
                    # 本サーバーは持ち時間管理を行わない(§26.11)ためダミー値"T1"を送る。
                    sign = "+" if mover == "black" else "-"
                    self._send(f"{sign}{snapshot.last_move_csa},T1")
                last_move_number = snapshot.move_number
                continue

            if snapshot.status != _STATUS_PLAYING:
                self._send_end(snapshot)
                return

            if snapshot.turn == snapshot.user_side:
                # 人間の手番: クライアントからの入力をブロッキング受信する
                # (人間がどれだけ長考してもタイムアウトさせない、02_design.md §26.4)。
                line = self._recv_line()
                if line is None:
                    return
                if line.startswith("%TORYO"):
                    self._submit_move("%TORYO")
                    continue
                sign = line[:1]
                expected_sign = "+" if snapshot.turn == "black" else "-"
                if sign != expected_sign:
                    continue  # 手番と符号が一致しない行は無視する(防御的)
                csa_move = line[1:].split(",")[0]
                result = self._submit_move(csa_move)
                if not result.get("ok"):
                    # 不正な指し手(02_design.md §26.8)。対局を中断してこの接続を閉じる
                    # (対局セッション自体はKIF自動保存済みのため/shogi-resumeで再開できる)。
                    self._send("#CHUDAN")
                    return
                # CSAプロトコルの標準的な挙動として、サーバーは受理した指し手を
                # 送信元のクライアントにもエコーバックする。実クライアント(ShogiHome)は
                # 自分の指し手もこのエコー経由でしか棋譜に反映しないため、エコーが
                # 無いと(自分の手番が進まないまま)次の相手の指し手を受信した時点で
                # 手番不整合("Invalid turn")エラーになることを実機確認した。
                self._send(f"{sign}{csa_move},T1")
            else:
                # Claude側の手番: apply_moveが反映されるのを待つ。素のtime.sleep()だと
                # クライアントが切断してもこの接続を保持し続け(connection_lockが
                # 解放されず再接続を阻害する、実機テストで発覚)、次にClaude側が指す
                # まで気づけない。MSG_PEEKによる非破壊的な読み取りをタイムアウト付きで
                # 行い、切断(recv()が空バイト列を返す)を待機中にも検知する。
                self._conn.settimeout(_POLL_INTERVAL)
                try:
                    peeked = self._conn.recv(1, socket.MSG_PEEK)
                    if peeked == b"":
                        return  # クライアントが切断した
                except socket.timeout:
                    pass
                finally:
                    self._conn.settimeout(None)

    def _send_end(self, snapshot: GameSnapshot) -> None:
        winner = _winner_side(snapshot.status, snapshot.turn)
        if winner is None:
            self._send("#DRAW")
        elif winner == snapshot.user_side:
            self._send("#WIN")
        else:
            self._send("#LOSE")


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], get_snapshot: GetSnapshot, submit_move: SubmitMove):
        self.get_snapshot = get_snapshot
        self.submit_move = submit_move
        # 同時に1接続のみ受け付ける(対局セッション自体が単一モデルのため、02_design.md §26.3)。
        self.connection_lock = threading.Lock()
        super().__init__(address, _Handler)

    def server_bind(self) -> None:
        # socketserver.TCPServerにはserver_port属性が無い(http.server.HTTPServerのみ
        # 提供する)。port=0(OS割当)でのテストのためにここで同じ仕組みを追加する。
        super().server_bind()
        self.server_port = self.socket.getsockname()[1]


class _Handler(socketserver.BaseRequestHandler):
    server: _Server

    def handle(self) -> None:
        if not self.server.connection_lock.acquire(blocking=False):
            try:
                self.request.sendall(_csa_line("LOGIN:incorrect"))
            except OSError:
                pass
            return
        try:
            _ConnectionHandler(self.request, self.server.get_snapshot, self.server.submit_move).run()
        finally:
            self.server.connection_lock.release()


def start(
    get_snapshot: GetSnapshot,
    submit_move: SubmitMove,
    port: int = PORT,
) -> Optional[_Server]:
    """CSAサーバーをデーモンスレッドで起動し、`_Server`を返す(テスト用に停止できるように)。

    127.0.0.1のみに待受を限定する(接続元は同一マシン上のCSA対応クライアントのみを
    想定、02_design.md §26.2)。ポートが使用中の場合は警告を出すのみでMCPサーバー本体
    (対局機能)は継続動作させる(gui_server.pyと同じ方針)。失敗時はNoneを返す。
    """
    try:
        server = _Server(("127.0.0.1", port), get_snapshot, submit_move)
    except OSError as e:
        print(f"[csa_server] failed to start on port {port}: {e}. CSA mode will be unavailable.")
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[csa_server] listening for CSA connections on 127.0.0.1:{server.server_port}")
    return server
