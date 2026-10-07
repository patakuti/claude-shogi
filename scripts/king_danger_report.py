#!/usr/bin/env python3
"""KIFの各局面で、玉への攻守の駒数比較(king_safety.own_king/opponent_king)を一覧する(02_design.md §41.5)。

指定した側(既定: 名前に"Claude"を含む側)の手番局面ごとに、自玉の攻め駒・守り駒・level を出す。
やねうら王の評価値(--referee)は表示するだけで、levelのしきい値の調整には使わない。

実行例(mcp-server/ から):
  uv run python ../scripts/king_danger_report.py ../games/2026-10-06_173352.kif --referee
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cshogi
from cshogi import KIF

from shogi_mcp import analysis

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_strength import ENGINE_PATH, Referee, claude_positions  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kif")
    ap.add_argument("--referee", action="store_true", help="やねうら王の評価値(手番側視点、キャッシュ利用)も表示する")
    ap.add_argument("--from-ply", type=int, default=0)
    ap.add_argument("--cache", default=str(Path(__file__).parent / ".strength_cache.json"))
    args = ap.parse_args()

    referee = Referee(500, 4, Path(args.cache)) if args.referee and ENGINE_PATH.exists() else None
    print(f"{'手':>4} {'自玉(攻盤/攻持/守/差)':<22}{'level':<8}{'相手玉(攻盤/攻持/守/差)':<24}{'level':<8}{'material差':>9}{'YO':>7}")
    try:
        for ply, sfen, _move in claude_positions(args.kif):
            if ply < args.from_ply:
                continue
            board = cshogi.Board(sfen)
            ks = analysis.analyze(board, mate_ply=1, threat_ply=1)["king_safety"]
            o, p = ks["own_king"], ks["opponent_king"]
            black, white = analysis.material(board)
            diff = (black - white) if board.turn == cshogi.BLACK else (white - black)
            yo = referee.evaluate(sfen)["cp"] if referee else ""
            fmt = lambda k: f"{k['attackers_on_board']}/{k['attackers_in_hand']}/{k['defenders']}/{k['balance']:+d}"
            print(f"{ply + 1:>4} {fmt(o):<22}{o['level']:<8}{fmt(p):<24}{p['level']:<8}{diff:>9}{yo:>7}")
    finally:
        if referee:
            referee.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
