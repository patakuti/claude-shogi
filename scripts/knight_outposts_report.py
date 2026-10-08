#!/usr/bin/env python3
"""全棋譜の局面で、桂の居座り(king_safety.own_knight_outposts)の出現率と出た手数を出す(02_design.md §43.6)。

各局面で、手番側の自玉に対する相手の桂の居座り(on_board)と打ち込み先(drop_squares)を数える。
出現率が高すぎる(約1割超)と警告として使えないので、定義を絞る判断材料にする。
やねうら王は使わない(出現率の計測のみ)。

実行例(mcp-server/ から):
  uv run python ../scripts/knight_outposts_report.py
  uv run python ../scripts/knight_outposts_report.py ../games/2026-10-08_163132.kif --list
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import cshogi
from cshogi import KIF

from shogi_mcp import analysis


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kifs", nargs="*", help="KIFファイル(省略時はgames/*.kif)")
    ap.add_argument("--list", action="store_true", help="出た局面を手数ごとに一覧する")
    args = ap.parse_args()

    paths = args.kifs or sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "games" / "*.kif")))
    total = on_board_hits = drop_hits = 0
    for path in paths:
        try:
            parser = KIF.Parser.parse_file(path)
        except Exception:
            continue
        board = cshogi.Board(parser.sfen)
        rows = []
        for ply, move in enumerate(parser.moves, 1):
            board.push(move)
            if board.is_game_over():
                break
            result = analysis.knight_outposts(board, board.turn)
            total += 1
            on_board_hits += bool(result["on_board"])
            drop_hits += bool(result["drop_squares"])
            if result["on_board"] or result["drop_squares"]:
                rows.append((ply, result))
        if args.list:
            print(Path(path).name)
            for ply, result in rows:
                squares = ",".join(
                    f"{e['square']}{'*' if e['direct'] else ''}" for e in result["on_board"]
                )
                drops = ",".join(result["drop_squares"])
                print(f"  {ply:>3}手後 居座り[{squares}] 打込み[{drops}]")
    if total:
        print(
            f"局面{total}: 居座りあり {on_board_hits} ({100 * on_board_hits / total:.1f}%) / "
            f"打ち込み先あり {drop_hits} ({100 * drop_hits / total:.1f}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
