"""USIプロトコルでやねうら王(等)を同期的に制御するラッパー。

フェーズ1の実機検証で判明した重要な注意点:
標準入力に複数コマンドをまとめて書き込み、`go`の直後に`quit`を送ると、
エンジンが思考を完了する前に停止してしまうことがある。本モジュールは
常に`bestmove`を受け取ってから次のコマンドを送るため、この問題は発生しない。
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


class UsiEngineError(Exception):
    """エンジンプロセスとの通信に関する一般的なエラー。"""


class UsiTimeoutError(UsiEngineError):
    """想定時間内にエンジンからの応答が得られなかった場合のエラー。"""


@dataclass
class PvInfo:
    """`info`行1本分(MultiPVの1候補手分)の内容。"""

    multipv: int
    depth: Optional[int] = None
    score_cp: Optional[int] = None
    score_mate: Optional[int] = None
    nodes: Optional[int] = None
    pv: list[str] = field(default_factory=list)


@dataclass
class ThinkResult:
    """`go`コマンド1回分の思考結果。"""

    bestmove: str
    ponder: Optional[str] = None
    # multipv番号(1始まり)をキーにした最新のinfo行。MultiPV=1なら要素は1件。
    pvs: dict[int, PvInfo] = field(default_factory=dict)

    @property
    def primary(self) -> Optional[PvInfo]:
        """multipv=1の候補手(最善手の読み筋)。"""
        return self.pvs.get(1)


OptionValue = Union[str, int, bool]


class UsiEngine:
    """1個のUSIエンジンプロセスを起動し、同期的にやり取りするクラス。"""

    def __init__(self, engine_path: str, options: Optional[dict[str, OptionValue]] = None):
        self._engine_path = str(Path(engine_path).resolve())
        self._cwd = str(Path(self._engine_path).parent)
        self._options: dict[str, OptionValue] = dict(options or {})
        self._proc: Optional[subprocess.Popen] = None
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None

    # --- プロセスのライフサイクル ---------------------------------------

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = 30.0) -> None:
        """エンジンを起動し、usi/isreadyのハンドシェイクを完了させる。"""
        self._proc = subprocess.Popen(
            [self._engine_path],
            cwd=self._cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._lines = queue.Queue()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        deadline = time.monotonic() + timeout
        self._send("usi")
        self._wait_for("usiok", deadline)
        for name, value in self._options.items():
            self._send(f"setoption name {name} value {self._format_option(value)}")
        self._send("isready")
        self._wait_for("readyok", deadline)

    def quit(self, timeout: float = 5.0) -> None:
        """`quit`を送って正常終了を待つ。応答がなければ強制終了する。"""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._proc = None
            return
        try:
            self._send("quit")
            proc.wait(timeout=timeout)
        except Exception:
            proc.kill()
            proc.wait(timeout=5.0)
        finally:
            self._proc = None

    def restart(self, timeout: float = 30.0) -> None:
        """異常終了時などにプロセスを起動し直す。局面の復元は呼び出し側の責務。"""
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5.0)
            except Exception:
                pass
            self._proc = None
        self.start(timeout=timeout)

    def set_option(self, name: str, value: OptionValue) -> None:
        """USIオプションを設定する。起動中なら即座にsetoptionを送信する。"""
        self._options[name] = value
        if self.is_alive():
            self._send(f"setoption name {name} value {self._format_option(value)}")

    @staticmethod
    def _format_option(value: OptionValue) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    # --- 思考 -------------------------------------------------------------

    def go(
        self,
        sfen: str,
        moves: list[str],
        byoyomi_ms: int,
        timeout_margin_ms: int = 5_000,
    ) -> ThinkResult:
        """局面を送って思考させ、bestmoveが返るまで待つ。

        :param sfen: `position sfen`に渡す局面(通常はSTARTING_SFEN)。
        :param moves: 初期局面からの指し手(USI表記)のリスト。
        :param byoyomi_ms: 秒読み(ミリ秒)。
        :param timeout_margin_ms: byoyomiに加える読み取りタイムアウトの猶予。
        """
        if not self.is_alive():
            raise UsiEngineError("engine process is not running")

        position_cmd = f"position sfen {sfen}"
        if moves:
            position_cmd += " moves " + " ".join(moves)
        self._send(position_cmd)
        self._send(f"go byoyomi {byoyomi_ms}")

        deadline = time.monotonic() + (byoyomi_ms + timeout_margin_ms) / 1000.0
        result = ThinkResult(bestmove="resign")
        while True:
            line = self._read_line(deadline, context=f"go byoyomi {byoyomi_ms}")
            if line.startswith("info "):
                self._parse_info(line, result)
            elif line.startswith("bestmove"):
                self._parse_bestmove(line, result)
                return result

    # --- info/bestmoveのパース ---------------------------------------------

    @staticmethod
    def _parse_info(line: str, result: ThinkResult) -> None:
        tokens = line.split(" ")
        multipv = 1
        depth: Optional[int] = None
        score_cp: Optional[int] = None
        score_mate: Optional[int] = None
        nodes: Optional[int] = None
        pv: list[str] = []

        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok == "multipv" and i + 1 < len(tokens):
                i += 1
                multipv = int(tokens[i])
            elif tok == "depth" and i + 1 < len(tokens):
                i += 1
                depth = int(tokens[i])
            elif tok == "nodes" and i + 1 < len(tokens):
                i += 1
                nodes = int(tokens[i])
            elif tok == "score" and i + 2 < len(tokens):
                kind = tokens[i + 1]
                value = tokens[i + 2]
                if kind == "cp":
                    score_cp = int(value)
                elif kind == "mate":
                    # "mate 5" や "mate -3" 以外に "mate +" のような符号のみの
                    # 表記が使われる実装もあるため、数値変換できない場合は
                    # 詰み手数不明として符号だけ保持する(0扱いにしない)。
                    try:
                        score_mate = int(value)
                    except ValueError:
                        score_mate = 1 if value.startswith("+") else -1
                i += 2
            elif tok == "pv":
                pv = tokens[i + 1:]
                break
            i += 1

        result.pvs[multipv] = PvInfo(
            multipv=multipv,
            depth=depth,
            score_cp=score_cp,
            score_mate=score_mate,
            nodes=nodes,
            pv=pv,
        )

    @staticmethod
    def _parse_bestmove(line: str, result: ThinkResult) -> None:
        tokens = line.split(" ")
        result.bestmove = tokens[1] if len(tokens) > 1 else "resign"
        if "ponder" in tokens:
            idx = tokens.index("ponder")
            if idx + 1 < len(tokens):
                result.ponder = tokens[idx + 1]

    # --- 内部: プロセスI/O ---------------------------------------------------

    def _send(self, cmd: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise UsiEngineError("engine process is not running")
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._lines.put(line.rstrip("\n"))

    def _read_line(self, deadline: float, context: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UsiTimeoutError(f"timed out waiting for engine response ({context})")
        try:
            return self._lines.get(timeout=remaining)
        except queue.Empty:
            raise UsiTimeoutError(f"timed out waiting for engine response ({context})")

    def _wait_for(self, token: str, deadline: float) -> None:
        while True:
            line = self._read_line(deadline, context=f"waiting for '{token}'")
            if line == token:
                return
