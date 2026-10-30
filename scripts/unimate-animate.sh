#!/bin/bash
# 动画导出封装：动作 -> 带动画的 GLB/FBX。
#   bash scripts/unimate-animate.sh <采样目录> [输出目录]
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
cd "$UNIMATE_HOME" || exit 1
SAMPLES="${1:?用法: unimate-animate.sh <采样目录> [输出目录]}"
OUT="${2:-}"
if [ -n "$OUT" ]; then
  exec bash scripts/run_animate_motion.sh "$SAMPLES" "$OUT"
else
  exec bash scripts/run_animate_motion.sh "$SAMPLES"
fi
