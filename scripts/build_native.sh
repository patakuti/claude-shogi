#!/usr/bin/env bash
# ネイティブ実装(任意)をビルドする。未実行でもPython実装で動く(02_design.md §34, §36)。
# 評価関数と盤面・合法手生成(将来は探索も)を1つの共有ライブラリにまとめる。
# 必要なもの: gcc。Linux専用(他OSでは未検証)。
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
src_dir="$root/mcp-server/native"
out_dir="$root/mcp-server/src/shogi_mcp/_native"
mkdir -p "$out_dir"
gcc -O2 -Wall -Wextra -shared -fPIC \
    -o "$out_dir/libshogi_native.so" \
    "$src_dir"/*.c
rm -f "$out_dir/libshogi_eval.so"  # 旧名(フェーズ33)の残骸
echo "built: $out_dir/libshogi_native.so"
