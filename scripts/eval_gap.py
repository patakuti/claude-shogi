#!/usr/bin/env python3
"""静的評価と、やねうら王の評価値(採点専用)のずれを測る(02_design.md §40.5)。

評価関数の重みを決めるためには使わない(重みは設計文書の根拠で固定する)。
「現行評価でずれが大きい局面、特に玉が薄い局面で、変更後にずれが縮むか」を確認する
合否判定の道具。

対象局面: samples/*.kif と games/ の指定KIFの「Claudeが指した側」の局面。
指標は、手番側視点の静的評価(±CP_CLAMPに丸める)とやねうら王の評価値との平均絶対誤差(MAE)。
  - 全体 / 段階別 / 玉が薄い局面(どちらかの玉の囲いが金銀1枚以下) / 駒得差500以上の局面

実行例(mcp-server/ から):
  uv run python ../scripts/eval_gap.py --out /tmp/gap_base.json
  uv run python ../scripts/eval_gap.py --kif ../games/2026-10-06_173352.kif   # 手ごとの比較
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

import cshogi

from shogi_mcp import analysis

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_strength import (  # noqa: E402
    CP_CLAMP, ENGINE_PATH, PHASES, REPO_ROOT, Referee, claude_positions, clamp, phase_of,
)

THIN_SHELTER = 1
BIG_MATERIAL_DIFF = 500
DEFAULT_GAMES = ("2026-10-06_072108.kif", "2026-10-06_173352.kif")


def shelter_counts(board: cshogi.Board) -> tuple[int, int]:
    pieces = board.pieces
    return (
        analysis._king_shelter_count(pieces, cshogi.BLACK, board.king_square(cshogi.BLACK)),
        analysis._king_shelter_count(pieces, cshogi.WHITE, board.king_square(cshogi.WHITE)),
    )


def measure(referee: Referee, game: str, ply: int, sfen: str) -> dict:
    board = cshogi.Board(sfen)
    ref = referee.evaluate(sfen)["cp"]
    ev = clamp(analysis._eval_for_side_to_move(board))
    black_s, white_s = shelter_counts(board)
    black_m, white_m = analysis._material_of(board.pieces, board.pieces_in_hand)
    return {
        "game": game, "ply": ply, "phase": phase_of(ply), "sfen": sfen,
        "ref": ref, "eval": ev, "err": abs(ev - ref), "signed": ev - ref,
        "thin": min(black_s, white_s) <= THIN_SHELTER,
        "big": abs(black_m - white_m) >= BIG_MATERIAL_DIFF,
    }


def summarize(rows: list[dict]) -> str:
    groups = [(name, lambda r, n=name: r["phase"] == n) for name, _, _ in PHASES]
    groups += [("全体", lambda r: True), ("玉が薄い", lambda r: r["thin"]), ("駒得差500以上", lambda r: r["big"]),
               ("駒得差500以上かつ玉が薄い", lambda r: r["big"] and r["thin"])]
    lines = [f"{'区分':<26}{'局面数':>6}{'MAE':>8}{'平均符号付き誤差':>14}"]
    for name, pred in groups:
        sel = [r for r in rows if pred(r)]
        if sel:
            lines.append(f"{name:<26}{len(sel):>6}{statistics.mean(r['err'] for r in sel):>8.0f}"
                         f"{statistics.mean(r['signed'] for r in sel):>14.0f}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", default=str(REPO_ROOT / "samples" / "*.kif"))
    ap.add_argument("--games", nargs="*", default=[str(REPO_ROOT / "games" / g) for g in DEFAULT_GAMES])
    ap.add_argument("--kif", help="このKIFだけを対象に、手ごとの静的評価とやねうら王の評価を表示する")
    ap.add_argument("--referee-ms", type=int, default=500)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cache", default=str(Path(__file__).parent / ".strength_cache.json"))
    ap.add_argument("--out", help="行データをJSONで保存する")
    args = ap.parse_args()

    if not ENGINE_PATH.exists():
        print(f"engine not found: {ENGINE_PATH} (run scripts/setup_engine.sh)", file=sys.stderr)
        return 1
    paths = [args.kif] if args.kif else sorted(glob.glob(args.samples)) + args.games
    print(f"eval impl: {'native' if analysis._eval_native else 'python'}")

    referee = Referee(args.referee_ms, args.threads, Path(args.cache))
    rows: list[dict] = []
    try:
        for path in paths:
            for ply, sfen, _move in claude_positions(path):
                rows.append(measure(referee, Path(path).name, ply, sfen))
            referee.cache_path.write_text(json.dumps(referee.cache))
    finally:
        referee.close()

    if args.kif:
        print(f"{'ply':>4}{'評価':>8}{'やねうら王':>10}{'差':>8}  玉が薄い")
        for r in rows:
            print(f"{r['ply'] + 1:>4}{r['eval']:>8}{r['ref']:>10}{r['signed']:>8}  {'*' if r['thin'] else ''}")
    print(summarize(rows))
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
