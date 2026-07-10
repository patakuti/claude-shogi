"""localhost:8765でGUI盤面(SVG)とリプレイ(棋譜再生)を配信する軽量HTTPサーバー。

標準ライブラリの`http.server`のみに依存する(新規の外部依存を追加しない方針、02_design.md §7.1)。

リプレイモード(02_design.md §12.4)は`games/`のKIFファイルのみを入力とする読み取り専用機能で、
対局セッションには一切触れない(=対局中でも過去譜を再生できる。排他制御も不要)。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

import cshogi
from cshogi import KIF

PORT = 8765

NO_GAME_FRAGMENT = "<p>対局が開始されていません。</p>"

# エンジン評価値のコメント行(02_design.md §12.2)。符号は先手有利=正に正規化済み。
_EVAL_RE = re.compile(r"^eval (cp|mate):(-?\d+)(?:\s+pv:(.*))?$")

_ENDGAME_LABELS = {
    "%TORYO": "投了",
    "%SENNICHITE": "千日手",
    "%KACHI": "入玉宣言",
    "%JISHOGI": "持将棋",
    "%CHUDAN": "中断",
}

_INDEX_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>将棋盤</title>
</head>
<body>
<div id="board">読み込み中...</div>
<p><a href="/replay">対局の振り返り(リプレイ)</a></p>
<script>
async function refresh() {
  const res = await fetch("/board");
  document.getElementById("board").innerHTML = await res.text();
}
refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>
"""

_REPLAY_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>将棋リプレイ</title>
<style>
body { font-family: sans-serif; margin: 16px; }
#controls { margin: 8px 0; display: flex; align-items: center; gap: 8px; }
#slider { flex: 1; max-width: 480px; }
#main { display: flex; gap: 24px; flex-wrap: wrap; }
#side { max-width: 460px; }
#comment { white-space: pre-wrap; background: #f4f4f4; padding: 8px; border-radius: 4px; min-height: 3em; }
#graph { border: 1px solid #ccc; cursor: pointer; }
button { min-width: 3em; }
</style>
</head>
<body>
<h2>対局の振り返り</h2>
<p><a href="/">対局中の盤面へ戻る</a></p>
<select id="game"></select> <span id="status"></span>
<div id="controls">
  <button id="first">|◀</button>
  <button id="prev">◀</button>
  <input type="range" id="slider" min="0" max="0" value="0">
  <button id="next">▶</button>
  <button id="last">▶|</button>
  <span id="plyLabel"></span>
</div>
<div id="main">
  <div id="board"></div>
  <div id="side">
    <h3 id="moveinfo">-</h3>
    <p id="evalinfo"></p>
    <div id="comment"></div>
    <h4>評価値(先手有利が正)</h4>
    <svg id="graph" width="440" height="150"></svg>
  </div>
</div>
<script>
let data = null, file = null, ply = 0;
const $ = (id) => document.getElementById(id);

async function fetchJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }

async function loadGames() {
  const games = await fetchJSON("/replay/games");
  const sel = $("game");
  sel.innerHTML = "";
  for (const name of games) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    sel.appendChild(opt);
  }
  sel.onchange = () => selectGame(sel.value);
  if (games.length) { await selectGame(games[0]); }
  else { $("moveinfo").textContent = "棋譜がありません"; }
}

async function selectGame(name) {
  file = name;
  data = await fetchJSON("/replay/game?file=" + encodeURIComponent(name));
  $("slider").max = data.moves.length;
  $("status").textContent = data.status ? "(" + data.status + ")" : "";
  drawGraph();
  await goto(data.moves.length);
}

function evalY(ev, h) {
  // cpは±1500でクランプ、mateは±1600相当として端に張り付ける
  let v = ev.cp !== undefined ? Math.max(-1500, Math.min(1500, ev.cp)) : (ev.mate > 0 ? 1600 : -1600);
  return h / 2 - (v / 1600) * (h / 2 - 6);
}

function drawGraph() {
  const svg = $("graph"), w = svg.clientWidth || 440, h = svg.clientHeight || 150;
  const n = Math.max(1, data.moves.length);
  const x = (p) => 4 + (p / n) * (w - 8);
  let parts = [`<line x1="0" y1="${h/2}" x2="${w}" y2="${h/2}" stroke="#bbb"/>`];
  const pts = data.moves.filter(m => m.eval).map(m => `${x(m.ply)},${evalY(m.eval, h)}`);
  if (pts.length > 1) parts.push(`<polyline points="${pts.join(" ")}" fill="none" stroke="#d33" stroke-width="1.5"/>`);
  for (const m of data.moves) if (m.eval)
    parts.push(`<circle cx="${x(m.ply)}" cy="${evalY(m.eval, h)}" r="2" fill="#d33"/>`);
  parts.push(`<line id="cursor" x1="${x(ply)}" y1="0" x2="${x(ply)}" y2="${h}" stroke="#36c"/>`);
  svg.innerHTML = parts.join("");
  svg.onclick = (e) => {
    const rect = svg.getBoundingClientRect();
    goto(Math.round(((e.clientX - rect.left - 4) / (w - 8)) * n));
  };
}

async function goto(p) {
  if (!data) return;
  ply = Math.max(0, Math.min(data.moves.length, p));
  $("slider").value = ply;
  $("plyLabel").textContent = ply + " / " + data.moves.length;
  const res = await fetch(`/replay/board?file=${encodeURIComponent(file)}&ply=${ply}`);
  $("board").innerHTML = await res.text();
  const cursor = $("cursor");
  if (cursor) {
    const w = $("graph").clientWidth || 440, n = Math.max(1, data.moves.length);
    const cx = 4 + (ply / n) * (w - 8);
    cursor.setAttribute("x1", cx); cursor.setAttribute("x2", cx);
  }
  if (ply === 0) {
    $("moveinfo").textContent = "開始局面";
    $("evalinfo").textContent = "";
    $("comment").textContent = "";
    return;
  }
  const m = data.moves[ply - 1];
  $("moveinfo").textContent = `${m.ply}手目 ${m.ply % 2 === 1 ? "▲" : "△"}${m.kif}`;
  let ev = "";
  if (m.eval) {
    ev = m.eval.cp !== undefined ? `評価値 ${m.eval.cp > 0 ? "+" : ""}${m.eval.cp}`
      : `${m.eval.mate > 0 ? "先手" : "後手"}勝ち(${Math.abs(m.eval.mate)}手詰み)`;
    if (m.eval_pv && m.eval_pv.length) ev += `  読み筋: ${m.eval_pv.join(" ")}`;
  }
  $("evalinfo").textContent = ev;
  $("comment").textContent = m.comment || "";
}

$("first").onclick = () => goto(0);
$("prev").onclick = () => goto(ply - 1);
$("next").onclick = () => goto(ply + 1);
$("last").onclick = () => data && goto(data.moves.length);
$("slider").oninput = (e) => goto(parseInt(e.target.value, 10));
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") goto(ply - 1);
  if (e.key === "ArrowRight") goto(ply + 1);
});
loadGames();
</script>
</body>
</html>
"""


def _safe_kif_path(games_dir: Path, name: str) -> Optional[Path]:
    """fileパラメータをgames/直下のKIFファイルに限定する(トラバーサル拒否、02_design.md §12.4)。"""
    if not name or name != Path(name).name or not name.endswith(".kif"):
        return None
    path = games_dir / name
    return path if path.is_file() else None


def _list_games(games_dir: Path) -> list[str]:
    files = sorted(games_dir.glob("*.kif"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in files]


def _split_eval_and_comment(lines: list[str]) -> tuple[Optional[dict], Optional[list[str]], Optional[str]]:
    """コメント行から評価値行(eval ...)を分離し、(eval, eval_pv, 表示用コメント)を返す。"""
    ev = None
    ev_pv = None
    rest: list[str] = []
    for line in lines:
        m = _EVAL_RE.match(line)
        if m and ev is None:
            ev = {m.group(1): int(m.group(2))}
            if m.group(3):
                ev_pv = m.group(3).split()
        else:
            rest.append(line)
    return ev, ev_pv, ("\n".join(rest) if rest else None)


def _game_data(path: Path) -> dict:
    """1棋譜分のリプレイ用データ(指し手・評価値・コメント・結果)を組み立てる。"""
    parser = KIF.Parser.parse_file(str(path))
    comments = getattr(parser, "comments", None) or []
    board = cshogi.Board(parser.sfen)
    moves = []
    prev_move = None
    for index, move in enumerate(parser.moves):
        kif_str = KIF.move_to_kif(move, prev_move)
        raw = comments[index] if index < len(comments) and comments[index] else None
        ev, ev_pv, comment = _split_eval_and_comment(raw.split("\n")) if raw else (None, None, None)
        moves.append(
            {
                "ply": index + 1,
                "usi": cshogi.move_to_usi(move),
                "kif": kif_str,
                "eval": ev,
                "eval_pv": ev_pv,
                "comment": comment,
            }
        )
        board.push(move)
        prev_move = move
    status = _ENDGAME_LABELS.get(parser.endgame or "")
    if status is None and board.is_game_over():
        status = "詰み"
    return {"moves": moves, "status": status}


def _board_svg_at(path: Path, ply: int) -> str:
    """ply手目まで進めた局面のSVG(ply=0は開始局面)。範囲外のplyは末尾/先頭に丸める。"""
    parser = KIF.Parser.parse_file(str(path))
    board = cshogi.Board(parser.sfen)
    ply = max(0, min(len(parser.moves), ply))
    last = None
    for move in parser.moves[:ply]:
        board.push(move)
        last = move
    return str(board.to_svg(lastmove=last, scale=2.0))


def _make_handler(
    board_fragment: Callable[[], str],
    games_dir: Optional[Path],
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, obj) -> None:
            self._send(json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def _replay_file(self, query: dict) -> Optional[Path]:
            if games_dir is None:
                return None
            name = (query.get("file") or [""])[0]
            return _safe_kif_path(games_dir, name)

        def do_GET(self) -> None:  # noqa: N802 (http.server標準の命名)
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if url.path == "/":
                self._send(_INDEX_HTML)
            elif url.path == "/board":
                self._send(board_fragment())
            elif url.path == "/replay":
                self._send(_REPLAY_HTML)
            elif url.path == "/replay/games":
                self._send_json(_list_games(games_dir) if games_dir is not None else [])
            elif url.path == "/replay/game":
                path = self._replay_file(query)
                if path is None:
                    self.send_error(404)
                    return
                self._send_json(_game_data(path))
            elif url.path == "/replay/board":
                path = self._replay_file(query)
                if path is None:
                    self.send_error(404)
                    return
                try:
                    ply = int((query.get("ply") or ["0"])[0])
                except ValueError:
                    self.send_error(400)
                    return
                self._send(_board_svg_at(path, ply), "image/svg+xml; charset=utf-8")
            else:
                self.send_error(404)

        def log_message(self, format: str, *args) -> None:
            pass  # アクセスログでMCPサーバーの標準出力を汚さない

    return Handler


def start(
    board_fragment: Callable[[], str],
    games_dir: Optional[Path] = None,
    port: int = PORT,
) -> Optional[ThreadingHTTPServer]:
    """GUIサーバーをデーモンスレッドで起動し、`ThreadingHTTPServer`を返す(テスト用に停止できるように)。

    `games_dir`はリプレイモードが読むKIFの置き場所(通常は`games/`)。Noneの場合、
    リプレイの棋譜一覧は空になる。

    ポートが使用中の場合は警告を出すだけでMCPサーバー本体(対局機能)は継続動作させる
    (GUIが使えないことが対局機能全体を止める理由にはならない、02_design.md §7.1)。失敗時は`None`を返す。
    """
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(board_fragment, games_dir))
    except OSError as e:
        print(f"[gui_server] failed to start on port {port}: {e}. GUI board will be unavailable.")
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[gui_server] serving board at http://localhost:{server.server_port}/")
    return server
