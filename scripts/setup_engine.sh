#!/usr/bin/env bash
# やねうら王(NNUE)のビルドと評価関数の配置を行うスクリプト。
# 対象: Ubuntu 24.04 / AMD Ryzen 5 5600GT (Zen3, AVX2対応, AVX512非対応)
#
# 実行後、以下が生成される:
#   engine/YaneuraOu-by-gcc   ... 思考エンジン本体
#   engine/eval/nn.bin        ... NNUE評価関数(Háo, tanuki-チーム配布, GPLv3)
#
# 前提パッケージ: build-essential, git, p7zip-full, wget
#   sudo apt install build-essential git p7zip-full wget

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENGINE_DIR="$ROOT_DIR/engine"
WORK_DIR="$(mktemp -d)"

# 評価関数: Háo (tanuki-チーム, halfkp_256x2-32-32, GPLv3)
# 標準NNUEアーキテクチャ(YANEURAOU_ENGINE_NNUE)と一致することを確認済み。
EVAL_URL="https://github.com/nodchip/tanuki-/releases/download/tanuki-.halfkp_256x2-32-32.2023-05-08/tanuki-.halfkp_256x2-32-32.2023-05-08.7z"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "== 1/4: やねうら王ソースをclone =="
git clone --depth 1 https://github.com/yaneurao/YaneuraOu.git "$WORK_DIR/YaneuraOu"

echo "== 2/4: ビルド (TARGET_CPU=ZEN3, NNUE) =="
# ZEN3ターゲットはAVX2+BMI2を有効化しつつRyzen 5000番台向けに最適化される。
# AVX512命令は使用されないため、要件(AVX512ビルド不可)を満たす。
mkdir -p "$WORK_DIR/YaneuraOu/build"
make -C "$WORK_DIR/YaneuraOu/source" -f Makefile normal \
  TARGET_CPU=ZEN3 \
  YANEURAOU_EDITION=YANEURAOU_ENGINE_NNUE \
  COMPILER=g++ \
  TARGET=../build/YaneuraOu-by-gcc \
  -j"$(nproc)"

mkdir -p "$ENGINE_DIR"
cp "$WORK_DIR/YaneuraOu/build/YaneuraOu-by-gcc" "$ENGINE_DIR/YaneuraOu-by-gcc"

echo "== 3/4: 評価関数(Háo)のダウンロードと配置 =="
wget -q "$EVAL_URL" -O "$WORK_DIR/eval.7z"
7z x "$WORK_DIR/eval.7z" -o"$WORK_DIR/eval_extract" -y >/dev/null
mkdir -p "$ENGINE_DIR/eval"
cp "$WORK_DIR/eval_extract/eval/nn.bin" "$ENGINE_DIR/eval/nn.bin"
cp "$WORK_DIR/eval_extract/gpl-3.0.txt" "$ENGINE_DIR/eval/LICENSE-eval-gpl-3.0.txt"

echo "== 4/4: USI疎通確認 =="
cd "$ENGINE_DIR"
RESULT=$( (echo "usi"; echo "setoption name USI_OwnBook value false"; \
  echo "isready"; sleep 1; echo "position startpos"; echo "go byoyomi 1000"; \
  sleep 2; echo "quit") | timeout 15 ./YaneuraOu-by-gcc 2>&1)

if echo "$RESULT" | grep -q "^bestmove"; then
  echo "OK: bestmoveを取得しました。"
  echo "$RESULT" | grep "^bestmove"
else
  echo "NG: bestmoveが取得できませんでした。以下は実行ログです。" >&2
  echo "$RESULT" >&2
  exit 1
fi

echo ""
echo "セットアップ完了:"
echo "  engine/YaneuraOu-by-gcc"
echo "  engine/eval/nn.bin"
