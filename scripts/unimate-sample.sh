#!/bin/bash
# 采样封装：文本 -> 动作。参数原样传给 unimate.inference.sample。
#   bash scripts/unimate-sample.sh --asset <rig 目录> --prompt "An object walks forward."
# 权重目录默认取 config.env 的 UNIMATE_EXP，可用 EXP_DIR 环境变量覆盖。
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
cd "$UNIMATE_HOME" || exit 1
exec "$PY" -m unimate.inference.sample --exp_dir "$EXP_DIR" "$@"
