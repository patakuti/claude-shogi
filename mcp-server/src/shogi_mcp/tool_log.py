"""思考用ツール呼び出しのJSONLログ(02_design.md §39)。

実戦で探索の挙動(深さ・時間・打ち切り)とClaudeの選択を後から検証できるよう、対局のKIFと
同じ場所に`<KIF名>.toollog.jsonl`を追記する。ログの失敗はツールの結果に影響させない。
`SHOGI_MCP_TOOLLOG=0`で無効化できる。
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_MAX_STR = 200


def enabled() -> bool:
    return os.environ.get("SHOGI_MCP_TOOLLOG") != "0"


def log_path(kif_path: Optional[Path]) -> Optional[Path]:
    """KIFのパスから対応するログのパスを返す。KIFが未確定ならNone。"""
    return Path(kif_path).with_suffix(".toollog.jsonl") if kif_path else None


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_MAX_STR]
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in value]
    return value


# --- 結果の要約(大きなフィールドは含めない) -----------------------------------


def _summarize_rank_moves(result: dict) -> dict:
    return {
        "legal_count": result.get("legal_count"),
        "depth": result.get("depth"),
        "depth_requested": result.get("depth_requested"),
        "time_limited": result.get("time_limited"),
        "top_tied": result.get("top_tied"),
        "mates": len(result.get("mates", [])),
        "allows_mate_count": result.get("allows_mate_count"),
        "top": [
            {k: e.get(k) for k in ("usi", "score", "material_change")} for e in result.get("top", [])[:3]
        ],
    }


def _summarize_verify_moves(result: dict) -> dict:
    keys = ("usi", "legal", "search_depth_completed", "search_truncated", "material_change", "allows_mate")
    return {"results": [{k: e.get(k) for k in keys} for e in result.get("results", [])]}


def _summarize_apply_move(result: dict) -> dict:
    return {"ok": result.get("ok"), "error": result.get("error")}


def _summarize_ok_only(result: dict) -> dict:
    return {"ok": result.get("ok")}


SUMMARIZERS: dict[str, Callable[[dict], dict]] = {
    "rank_moves": _summarize_rank_moves,
    "verify_moves": _summarize_verify_moves,
    "analyze_position": _summarize_ok_only,
    "simulate_line": _summarize_ok_only,
    "apply_move": _summarize_apply_move,
}


def record(path: Path, tool: str, ply: Optional[int], elapsed_ms: int, args: dict, result: Any) -> None:
    summarize = SUMMARIZERS.get(tool, _summarize_ok_only)
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "tool": tool,
        "ply": ply,
        "elapsed_ms": elapsed_ms,
        "args": {k: _clip(v) for k, v in args.items()},
        "summary": summarize(result) if isinstance(result, dict) else {},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def logged(tool: str, context: Callable[[], tuple[Optional[Path], Optional[int]]]):
    """ツール関数をログ付きにするデコレータ。`context()`は(KIFのパス, 手数)を返す。

    ログの書き込み・要約の例外は握りつぶし、標準エラーに1行出すだけにする。
    `functools.wraps`でシグネチャを保つ(FastMCPが引数スキーマを作るため)。
    """

    def decorate(fn: Callable) -> Callable:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            active = enabled()
            before: tuple[Optional[Path], Optional[int]] = (None, None)
            if active:
                try:
                    before = context()  # 手数は呼び出し前(これから読む/指す局面)の値
                except Exception as exc:  # noqa: BLE001
                    print(f"[tool_log] failed to read context for {tool}: {exc!r}", file=sys.stderr)
            result = fn(*args, **kwargs)
            if active:
                try:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    kif_path, ply = before
                    path = log_path(kif_path)
                    if path is not None:
                        bound = signature.bind(*args, **kwargs)
                        bound.apply_defaults()
                        record(path, tool, ply, elapsed_ms, dict(bound.arguments), result)
                except Exception as exc:  # noqa: BLE001 - ログの失敗で本処理を止めない
                    print(f"[tool_log] failed to log {tool}: {exc!r}", file=sys.stderr)
            return result

        return wrapper

    return decorate
