"""難易度プリセット。

やねうら王の実機ビルドにはSkillLevelオプションが存在しないことを実測確認済み(02_design.md §4)。
NodesLimit(探索ノード数上限)とbyoyomi(秒読み)の組み合わせのみで難易度を構成する。
ここに挙げるノード数は初期値であり、フェーズ5の実対局を通じて調整する。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LEVEL = 1


@dataclass(frozen=True)
class Difficulty:
    level: int
    label: str
    nodes_limit: int  # 0 = 無制限
    byoyomi_ms: int
    threads: int


PRESETS: dict[int, Difficulty] = {
    1: Difficulty(level=1, label="入門", nodes_limit=1_000, byoyomi_ms=100, threads=1),
    2: Difficulty(level=2, label="初級", nodes_limit=10_000, byoyomi_ms=300, threads=2),
    3: Difficulty(level=3, label="中級", nodes_limit=100_000, byoyomi_ms=1_000, threads=4),
    4: Difficulty(level=4, label="上級", nodes_limit=0, byoyomi_ms=2_000, threads=4),
    5: Difficulty(level=5, label="最強", nodes_limit=0, byoyomi_ms=5_000, threads=8),
}


def get(level: int) -> Difficulty:
    if level not in PRESETS:
        raise ValueError(f"invalid difficulty level: {level} (must be 1-{len(PRESETS)})")
    return PRESETS[level]
