#!/usr/bin/env python3
"""rank_moves の強さを、過去の対局の局面でオフライン採点する(02_design.md §35.3)。

samples/ のKIFから「Claudeが指した側」の局面を取り出し、やねうら王(採点専用。対局の
手の決定には使わない)が最善とする手・評価値と、rank_moves の上位手を比べる。

  - top1:  rank_moves の1位手がやねうら王の最善手と一致した割合
  - top3:  最善手が rank_moves の上位3手に含まれた割合
  - loss:  rank_moves の1位手を指した場合の評価損(cp、やねうら王の評価で、最善手との差)
  - actual: 実戦でClaudeが指した手の評価損(参考)

局面の段階: 序盤(〜30手) / 中盤(31〜80手) / 終盤(81手〜)。
やねうら王の結果は --cache に保存し、同じ局面は再計算しない。

実行例(mcp-server/ から):
  uv run python ../scripts/measure_strength.py --depths 1,2 --out /tmp/baseline.json
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
import time
from pathlib import Path

import cshogi
from cshogi import KIF

from shogi_mcp import analysis
from shogi_mcp.usi_engine import UsiEngine

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = REPO_ROOT / "engine" / "YaneuraOu-by-gcc"
CP_CLAMP = 2000  # 詰みや大差による評価損の極端な値を抑える
PHASES = (("序盤(~30手)", 0, 30), ("中盤(31~80手)", 30, 80), ("終盤(81手~)", 80, 10_000))


def clamp(cp: int) -> int:
    return max(-CP_CLAMP, min(CP_CLAMP, cp))


class Referee:
    """やねうら王による採点。結果はsfen単位でキャッシュする。"""

    def __init__(self, byoyomi_ms: int, threads: int, cache_path: Path):
        self.byoyomi_ms = byoyomi_ms
        self.cache_path = cache_path
        self.cache: dict[str, dict] = {}
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text())
        self.engine = UsiEngine(
            str(ENGINE_PATH),
            options={"USI_Hash": 256, "Threads": threads, "USI_Ponder": False, "USI_OwnBook": False},
        )
        self.engine.start()

    def close(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache))
        self.engine.quit()

    def evaluate(self, sfen: str) -> dict:
        """手番側視点の {"best": usi, "cp": int}。詰みは±CP_CLAMPに丸める。"""
        key = f"{self.byoyomi_ms}|{sfen}"
        if key not in self.cache:
            result = self.engine.go(sfen, [], self.byoyomi_ms)
            primary = result.primary
            cp = 0
            if primary is not None:
                if primary.score_mate is not None:
                    cp = CP_CLAMP if primary.score_mate > 0 else -CP_CLAMP
                elif primary.score_cp is not None:
                    cp = clamp(primary.score_cp)
            self.cache[key] = {"best": result.bestmove, "cp": cp}
        return self.cache[key]

    def value_after(self, board: cshogi.Board, move: int) -> int:
        """moveを指した後の、指した側視点の評価値。"""
        copy = cshogi.Board(board.sfen())
        copy.push(move)
        if copy.is_game_over():
            return CP_CLAMP  # 詰ませた(自分が詰まされる手は合法手にない)
        return -self.evaluate(copy.sfen())["cp"]


def claude_positions(kif_path: str):
    parsed = KIF.Parser.parse_file(kif_path)
    board = cshogi.Board(parsed.sfen)
    claude_colors = {i for i, name in enumerate(parsed.names) if "Claude" in name}
    for ply, move in enumerate(parsed.moves):
        if board.turn in claude_colors:
            yield ply, board.sfen(), move
        board.push(move)


def phase_of(ply: int) -> str:
    for name, lo, hi in PHASES:
        if lo <= ply < hi:
            return name
    return PHASES[-1][0]


def summarize(rows: list[dict]) -> str:
    lines = [f"{'段階':<14}{'局面数':>6}{'top1':>8}{'top3':>8}{'loss(cp)':>10}{'actual':>9}{'秒/手':>8}"]
    for name in [p[0] for p in PHASES] + ["全体"]:
        sel = [r for r in rows if name == "全体" or r["phase"] == name]
        if not sel:
            continue
        n = len(sel)
        lines.append(
            f"{name:<14}{n:>6}"
            f"{100 * sum(r['top1'] for r in sel) / n:>7.0f}%"
            f"{100 * sum(r['top3'] for r in sel) / n:>7.0f}%"
            f"{statistics.mean(r['loss'] for r in sel):>10.0f}"
            f"{statistics.mean(r['actual_loss'] for r in sel):>9.0f}"
            f"{statistics.mean(r['seconds'] for r in sel):>8.2f}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", default=str(REPO_ROOT / "samples" / "*.kif"))
    ap.add_argument("--depths", default="1", help="rank_moves の depth(カンマ区切り、例: 1,2)")
    ap.add_argument("--referee-ms", type=int, default=500, help="やねうら王の秒読み(ミリ秒)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cache", default=str(Path(__file__).parent / ".strength_cache.json"))
    ap.add_argument("--node-limit", type=int, default=analysis.DEFAULT_NODE_LIMIT,
                    help="rank_moves の候補手ごとのノード上限(深さ4以上を測るときに引き上げる)")
    ap.add_argument("--stride", type=int, default=1, help="N局面おきに抽出する(深い探索を短時間で測るため)")
    ap.add_argument("--max-positions", type=int, default=0, help="局面数の上限(0=全て。動作確認用)")
    ap.add_argument("--out", help="結果の行データをJSONで保存する")
    args = ap.parse_args()

    if not ENGINE_PATH.exists():
        print(f"engine not found: {ENGINE_PATH} (run scripts/setup_engine.sh)", file=sys.stderr)
        return 1

    positions = []
    for path in sorted(glob.glob(args.samples)):
        for ply, sfen, move in claude_positions(path):
            positions.append((Path(path).name, ply, sfen, move))
    positions = positions[:: args.stride]
    if args.max_positions:
        positions = positions[: args.max_positions]
    print(f"positions: {len(positions)}  eval impl: {'native' if analysis._eval_native else 'python'}")

    referee = Referee(args.referee_ms, args.threads, Path(args.cache))
    all_rows: dict[int, list[dict]] = {}
    try:
        for depth in [int(d) for d in args.depths.split(",")]:
            rows = []
            for i, (name, ply, sfen, played) in enumerate(positions, 1):
                board = cshogi.Board(sfen)
                best = referee.evaluate(sfen)
                t0 = time.perf_counter()
                ranked = analysis.rank_moves(board, top_n=3, depth=depth, node_limit=args.node_limit)
                seconds = time.perf_counter() - t0
                candidates = [e["usi"] for e in ranked["mates"]] + [e["usi"] for e in ranked["top"]]
                if not candidates:
                    continue
                top1_move = board.move_from_usi(candidates[0])
                rows.append({
                    "game": name, "ply": ply, "phase": phase_of(ply), "sfen": sfen,
                    "top1": candidates[0] == best["best"],
                    "top3": best["best"] in candidates[:3],
                    "loss": max(0, best["cp"] - referee.value_after(board, top1_move)),
                    "actual_loss": max(0, best["cp"] - referee.value_after(board, played)),
                    "seconds": seconds, "top_tied": ranked["top_tied"],
                })
                if i % 50 == 0:
                    print(f"  depth {depth}: {i}/{len(positions)}", flush=True)
            all_rows[depth] = rows
            print(f"\n=== rank_moves depth={depth} ===\n{summarize(rows)}\n")
    finally:
        referee.close()
    if args.out:
        Path(args.out).write_text(json.dumps(all_rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
