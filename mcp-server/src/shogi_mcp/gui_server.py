"""localhost:8765でGUI盤面(SVG)を配信する軽量HTTPサーバー。

標準ライブラリの`http.server`のみに依存する(新規の外部依存を追加しない方針、02_design.md §7.1)。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

PORT = 8765

NO_GAME_FRAGMENT = "<p>対局が開始されていません。</p>"

_INDEX_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>将棋盤</title>
</head>
<body>
<div id="board">読み込み中...</div>
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


def _make_handler(board_fragment: Callable[[], str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server標準の命名)
            if self.path == "/":
                self._send(_INDEX_HTML)
            elif self.path == "/board":
                self._send(board_fragment())
            else:
                self.send_error(404)

        def log_message(self, format: str, *args) -> None:
            pass  # アクセスログでMCPサーバーの標準出力を汚さない

    return Handler


def start(board_fragment: Callable[[], str], port: int = PORT) -> Optional[ThreadingHTTPServer]:
    """GUIサーバーをデーモンスレッドで起動し、`ThreadingHTTPServer`を返す(テスト用に停止できるように)。

    ポートが使用中の場合は警告を出すだけでMCPサーバー本体(対局機能)は継続動作させる
    (GUIが使えないことが対局機能全体を止める理由にはならない、02_design.md §7.1)。失敗時は`None`を返す。
    """
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(board_fragment))
    except OSError as e:
        print(f"[gui_server] failed to start on port {port}: {e}. GUI board will be unavailable.")
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[gui_server] serving board at http://localhost:{server.server_port}/")
    return server
