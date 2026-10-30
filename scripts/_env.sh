#!/bin/bash
# 所有流水线脚本共用：定位仓库、加载 config.env、准备 Python 和工具路径。
# 用法：source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
set -uo pipefail

PIPELINE_HOME="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export PIPELINE_HOME

# config.env 不入库；没有就用环境变量（CI 里直接 export）
CONFIG_FILE="${PIPELINE_CONFIG:-$PIPELINE_HOME/config.env}"
if [ -f "$CONFIG_FILE" ]; then
  set -a
  . "$CONFIG_FILE"
  set +a
fi

: "${UNIMATE_HOME:?没有配置 UNIMATE_HOME（复制 config.example.env 为 config.env）}"
export UNIMATE_HOME

UNIMATE_PYTHON="${UNIMATE_PYTHON:-python3}"
PY="$(readlink -f "$UNIMATE_PYTHON")"
export UNIMATE_PYTHON="$PY"

# 让 tools/*.py 能 import pipeline_config / unimate_api
TOOLS="$PIPELINE_HOME/tools"
export PYTHONPATH="$TOOLS:${PYTHONPATH:-}"

# 把 UniMate 环境的 bin 放到 PATH 前面：bpy 的 blender shim 等都在里面
PYBIN="$(dirname "$PY")"
[ -d "$PYBIN" ] && export PATH="$PYBIN:$PATH"

# UniMate 的 bash 脚本要靠 conda 环境名找到解释器
export CONDA_ENV="${CONDA_ENV:-unimate}"

# xet 下载后端在本机网络下会挂住，走普通 HTTP
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

EXP_DIR="${EXP_DIR:-${UNIMATE_EXP:-outputs/unimate_uniml3d_f60_v3}}"
SAMPLES_HOME="${SAMPLES_HOME:-${UNIMATE_SAMPLES:-outputs/samples}}"
RIGS_HOME="${RIGS_HOME:-${UNIMATE_RIGS:-outputs/rig}}"
export EXP_DIR SAMPLES_HOME RIGS_HOME

# 相对路径按 UNIMATE_HOME 解析
from_unimate() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$UNIMATE_HOME" "$1" ;;
  esac
}
abs_path() { readlink -f "$1" 2>/dev/null || printf '%s/%s' "$PWD" "$1"; }
