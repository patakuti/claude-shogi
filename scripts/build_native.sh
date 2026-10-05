#!/usr/bin/env bash
# 評価関数のネイティブ実装(任意)をビルドする。未実行でもPython実装で動く(02_design.md §34)。
# 必要なもの: gcc。Linux専用(他OSでは未検証)。
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir="$root/mcp-server/src/shogi_mcp/_native"
mkdir -p "$out_dir"
gcc -O2 -Wall -Wextra -shared -fPIC \
    -o "$out_dir/libshogi_eval.so" \
    "$root/mcp-server/native/shogi_eval.c"
echo "built: $out_dir/libshogi_eval.so"
