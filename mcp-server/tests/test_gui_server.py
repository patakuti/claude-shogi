import urllib.error
import urllib.request

import pytest

from shogi_mcp import gui_server


@pytest.fixture
def running_server():
    server = gui_server.start(lambda: "<svg>dummy</svg>", port=0)
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
