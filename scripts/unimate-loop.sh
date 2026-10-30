#!/bin/bash
# 循环化一条龙：两条路线，二选一
#
#   默认（后处理）：起点 + 周期一起搜 -> 剪切 -> 导出 -> 拉平根位移 -> 打包 Unity
#   --close（模型闭环）：让模型把末帧收回首帧 -> 导出 -> 拉平 -> 打包
#
# 用法：
#   bash scripts/unimate-loop.sh --samples <采样目录> --name X_Bot --rig <rig.glb>
#   bash scripts/unimate-loop.sh --samples <采样目录> --name X_Bot --rig <rig.glb> --close
#
#   --samples <dir>   采样目录（含 motions/ 和 manifest.json）
#   --name <str>      角色名
#   --rig <path>      canonical 资产（<RIGS_HOME>/<name>/<name>.glb）
#   --exp-dir <dir>   权重目录，默认 config.env 的 UNIMATE_EXP（--close 必填到能用）
#   --close           走模型闭环路线
#   --pin-tail <n>    闭环时钉住末 n 帧，默认 2（位置 + 速度都约束）
#   --seam <n>        后处理路线接缝淡化帧数，默认 4
#   --out <dir>       输出目录，默认 <samples>_loop
#   --no-bundle       不打包 Unity 目录
#   --dry-run         只打印命令

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"

SAMPLES=""; NAME=""; RIG=""; SEAM=4; PIN=2; OUT=""; BUNDLE=1; DRY=0; CLOSE=0

need_val() { [ $# -ge 2 ] || { echo "参数 $1 需要一个值" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --samples)   need_val "$@"; SAMPLES="$2"; shift 2 ;;
    --name)      need_val "$@"; NAME="$2"; shift 2 ;;
    --rig)       need_val "$@"; RIG="$2"; shift 2 ;;
    --exp-dir)   need_val "$@"; EXP_DIR="$2"; shift 2 ;;
    --seam)      need_val "$@"; SEAM="$2"; shift 2 ;;
    --pin-tail)  need_val "$@"; PIN="$2"; shift 2 ;;
    --out)       need_val "$@"; OUT="$2"; shift 2 ;;
    --close)     CLOSE=1; shift ;;
    --no-bundle) BUNDLE=0; shift ;;
    --dry-run)   DRY=1; shift ;;
    -h|--help)   sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$SAMPLES" ] || { echo "缺少 --samples" >&2; exit 2; }
SAMPLES="$(abs_path "$SAMPLES")"
[ -d "$SAMPLES" ] || { echo "找不到目录：$SAMPLES" >&2; exit 2; }
[ -n "$RIG" ] && RIG="$(abs_path "$RIG")"
[ -n "$NAME" ] || NAME=$(basename "$SAMPLES")
[ -n "$OUT" ] || OUT="$(dirname "$SAMPLES")/$(basename "$SAMPLES")_loop"
OUT="$(abs_path "$OUT")"
RIG_DIR=""
[ -n "$RIG" ] && RIG_DIR="$(dirname "$RIG")"

run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; return 0; fi; echo "  \$ $*"; "$@"; }

echo "============================================================"
echo "采样目录: $SAMPLES"
echo "输出    : $OUT"
echo "角色    : $NAME"
if [ "$CLOSE" = 1 ]; then echo "路线    : 模型闭环（钉末 $PIN 帧）"; else echo "路线    : 后处理（淡化 $SEAM 帧）"; fi
echo "============================================================"

if [ "$CLOSE" = 1 ]; then
  echo
  echo "== [0/3] 模型闭环：让模型把末帧收回首帧"
  [ -n "$RIG_DIR" ] || { echo "  缺少 --rig，闭环建 cond 需要它" >&2; exit 2; }
  WORK="$OUT/closed"
  run "$PY" "$TOOLS/loop_close.py" --samples "$SAMPLES" --exp-dir "$EXP_DIR" \
      --asset "$RIG_DIR" --out "$WORK" --pin-tail "$PIN"
else
  echo
  echo "== [0/3] 起点 + 周期一起搜，剪切 + 接缝淡化"
  WORK="$OUT"
  run "$PY" "$TOOLS/make_loop.py" --samples "$SAMPLES" --seam "$SEAM" --out "$WORK"
fi

echo
echo "== [1/3] 导出 GLB / FBX"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] bash $PIPELINE_HOME/scripts/unimate-animate.sh $WORK"
else
  bash "$PIPELINE_HOME/scripts/unimate-animate.sh" "$WORK" 2>&1 | tail -2
fi

echo
echo "== [2/3] 拉平根位移（原地）"
run "$PY" "$TOOLS/flatten_root.py" --input "$WORK/animated" --out "$WORK/animated_inplace"

echo
echo "== [3/3] 打包 Unity 目录"
if [ "$BUNDLE" = 1 ]; then
  if [ -z "$RIG" ]; then
    echo "  跳过：没给 --rig"
  else
    run "$PY" "$TOOLS/bundle_unity.py" --samples "$SAMPLES" \
        --animated "$WORK/animated_inplace" --rig "$RIG" --name "$NAME" --out "$WORK/unity"
  fi
else
  echo "  跳过（--no-bundle）"
fi

echo
echo "============================================================"
echo "产物："
echo "  循环动作特征 : $WORK/motions/*.npy"
if [ "$CLOSE" = 1 ]; then echo "  闭环报告     : $WORK/loop_close_report.json"; else echo "  接缝报告     : $WORK/loop_report.json"; fi
echo "  原地 FBX     : $WORK/animated_inplace/*.fbx   <- Unity 用这个"
echo "  Unity 目录   : $WORK/unity/"
echo "完成"