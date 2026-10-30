#!/bin/bash
# 一条龙：体检 -> (超标才精简) -> rig_preprocess -> 采样 -> 导出 GLB/FBX
# 每一步都先判断能不能跳过。
#
# 用法：
#   bash scripts/unimate-pipeline.sh --input "Arts/X Bot.fbx"
#   bash scripts/unimate-pipeline.sh --input robot.fbx --name robot \
#       --prompt "An object walks forward." --prompt "An object runs forward." --reps 2
#   bash scripts/unimate-pipeline.sh --input a.fbx --drop "Finger|Twist" --max-joints 71
#
#   --input <file>       rigged GLB / glTF / FBX（必填）
#   --name <str>         资产名，默认由文件名推出来
#   --exp-dir <dir>      权重目录，默认 config.env 的 UNIMATE_EXP
#   --prompt <str>       可重复；默认 待机/走/跑 三条
#   --reps <n>           每个 prompt 采几次，默认 3
#   --drop <re>          --mode drop 用的正则（非 Mixamo 骨架）
#   --keep <re>          --mode keep 用的正则
#   --max-joints <n>     通用权重的关节上限，默认 71
#   --target-joints <n>  手动指定目标关节数（默认按权重自动定）
#   --out <dir>          采样输出目录，默认 <SAMPLES_HOME>/<name>
#   --stop-after <step>  inspect|simplify|rig|sample
#   --force              rig_preprocess 重跑
#   --dry-run            只打印计划

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"

INPUT=""; NAME=""; PROMPTS=(); DROPS=(); KEEPS=()
MAX_JOINTS=71; TARGET_JOINTS=""; REPS=3; FORCE=0; DRY=0; STOP_AFTER=""; OUT_SAMPLES=""

need_val() { [ $# -ge 2 ] || { echo "参数 $1 需要一个值" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --input)         need_val "$@"; INPUT="$2"; shift 2 ;;
    --name)          need_val "$@"; NAME="$2"; shift 2 ;;
    --exp-dir)       need_val "$@"; EXP_DIR="$2"; shift 2 ;;
    --prompt)        need_val "$@"; PROMPTS+=("$2"); shift 2 ;;
    --drop)          need_val "$@"; DROPS+=("$2"); shift 2 ;;
    --keep)          need_val "$@"; KEEPS+=("$2"); shift 2 ;;
    --max-joints)    need_val "$@"; MAX_JOINTS="$2"; shift 2 ;;
    --target-joints) need_val "$@"; TARGET_JOINTS="$2"; shift 2 ;;
    --reps)          need_val "$@"; REPS="$2"; shift 2 ;;
    --out)           need_val "$@"; OUT_SAMPLES="$2"; shift 2 ;;
    --stop-after)    need_val "$@"; STOP_AFTER="$2"; shift 2 ;;
    --force)         FORCE=1; shift ;;
    --dry-run)       DRY=1; shift ;;
    -h|--help)       sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$INPUT" ] || { echo "缺少 --input" >&2; exit 2; }
INPUT="$(abs_path "$INPUT")"
[ -f "$INPUT" ] || { echo "找不到文件：$INPUT" >&2; exit 2; }

stem=$(basename "${INPUT%.*}")
safe=$("$PY" -c "import re,sys;print(re.sub(r'[- \t\[\]?*]+','_',sys.argv[1]).strip('_') or 'asset')" "$stem")
[ -n "$NAME" ] || NAME="$safe"
[ -n "$OUT_SAMPLES" ] || OUT_SAMPLES="$SAMPLES_HOME/$NAME"
[ ${#PROMPTS[@]} -gt 0 ] || PROMPTS=("An object stands still." "An object walks forward." "An object runs forward.")

# 目标关节数：人体专用权重（目录名带 mixamo）固定 22 根；通用权重用 --max-joints
if [ -n "$TARGET_JOINTS" ]; then
  TARGET="$TARGET_JOINTS"; TARGET_WHY="用户指定"
elif printf '%s' "$EXP_DIR" | grep -qi mixamo; then
  TARGET=22; TARGET_WHY="人体专用权重只吃 22 关节 Mixamo 骨架"
else
  TARGET="$MAX_JOINTS"; TARGET_WHY="通用权重上限"
fi

TMP="$PIPELINE_HOME/tmp/$NAME"
mkdir -p "$TMP"

run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; return 0; fi; echo "  \$ $*"; "$@"; }

echo "============================================================"
echo "资产    : $INPUT"
echo "名称    : $NAME"
echo "权重    : $EXP_DIR"
echo "关节上限: $MAX_JOINTS    目标关节: $TARGET（$TARGET_WHY）"
echo "prompt  : ${PROMPTS[*]}"
echo "重采    : $REPS"
echo "============================================================"

# ---------------- 1. 体检 ----------------
echo
echo "== [1/5] 体检"
INSPECT_JSON=$TMP/inspect.json
"$PY" "$TOOLS/inspect_rig.py" --input "$INPUT" --json "$INSPECT_JSON" --no-bones 2>&1 \
  | grep -vE "User property type|^FBX version" || true
BONES=$("$PY" -c "import json;print(json.load(open('$INSPECT_JSON'))['bone_count'])" 2>/dev/null)
[ -n "$BONES" ] || BONES=-1
echo "  关节数: $BONES（目标 $TARGET）"
[ "$STOP_AFTER" = "inspect" ] && { echo; echo "已停止在体检步骤"; exit 0; }

# ---------------- 2. 精简（只在超标时） ----------------
CURRENT_ASSET="$INPUT"
if [ "$BONES" -gt 0 ] && [ "$BONES" -le "$TARGET" ]; then
  echo
  echo "== [2/5] 精简：跳过（$BONES 根 <= $TARGET）"
else
  echo
  echo "== [2/5] 精简：$BONES 根 > $TARGET，需要精简（$TARGET_WHY）"
  SIM_ARGS=("$TOOLS/simplify_rig.py" --input "$INPUT" --max-joints "$TARGET" --report "$TMP/simplify.report.json")
  if [ ${#DROPS[@]} -gt 0 ]; then
    SIM_ARGS+=(--mode drop); for d in "${DROPS[@]}"; do SIM_ARGS+=(--drop "$d"); done
  elif [ ${#KEEPS[@]} -gt 0 ]; then
    SIM_ARGS+=(--mode keep); for k in "${KEEPS[@]}"; do SIM_ARGS+=(--keep "$k"); done
  else
    SIM_ARGS+=(--mode mixamo)
  fi
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] $PY ${SIM_ARGS[*]}"
    CURRENT_ASSET="<精简后的资产>"
  else
    "$PY" "${SIM_ARGS[@]}" 2>&1 | grep -vE "User property type|WARNING: Animation target|^FBX version" || true
    CURRENT_ASSET=$("$PY" -c "import json;print(json.load(open('$TMP/simplify.report.json'))['outputs'][0])" 2>/dev/null)
    [ -n "$CURRENT_ASSET" ] || { echo "精简没有产出文件，停止" >&2; exit 1; }
    echo "  精简后: $CURRENT_ASSET"
  fi
  [ "$STOP_AFTER" = "simplify" ] && { echo; echo "已停止在精简步骤"; exit 0; }
fi

# ---------------- 3. rig_preprocess ----------------
echo
echo "== [3/5] rig_preprocess（打标签 / 烘 canonical）"
RIG_DIR="$RIGS_HOME/$NAME"
if [ -f "$RIG_DIR/cond.npy" ] && [ "$FORCE" = 0 ]; then
  echo "  跳过：$RIG_DIR/cond.npy 已存在（要重做加 --force）"
else
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] (cd $UNIMATE_HOME && $PY -m data_process.rig_preprocess run --input $CURRENT_ASSET --output_dir $RIG_DIR --name $NAME --no_review)"
  else
    mkdir -p "$(dirname "$RIG_DIR")"
    ( cd "$UNIMATE_HOME" && "$PY" -m data_process.rig_preprocess run \
        --input "$CURRENT_ASSET" --output_dir "$RIG_DIR" --name "$NAME" --no_review ) 2>&1 \
      | grep -vE "User property type|WARNING: Animation target|^FBX version|Processing objects" | tail -6
  fi
fi
if [ "$DRY" = 0 ] && [ -f "$RIG_DIR/summary.json" ]; then
  "$PY" -c "
import json
d = json.load(open('$RIG_DIR/summary.json'))
f = d.get('model_joint_limit', {}).get('fits')
print('  关节 %s  朝向对 %s  fits=%s' % (d.get('n_joints'), d.get('face_pair',{}).get('source'), f))
print('  看 preview.png：人要站直、面朝 +Z' if f else '  警告：fits=false')
" 2>/dev/null || true
fi
[ "$STOP_AFTER" = "rig" ] && { echo; echo "已停止在 rig 步骤"; exit 0; }

# ---------------- 4. 采样 ----------------
echo
echo "== [4/5] 采样（${#PROMPTS[@]} 个 prompt x $REPS 次）"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] bash $PIPELINE_HOME/scripts/unimate-sample.sh --asset $RIG_DIR --prompt ${PROMPTS[*]} --num_repetitions $REPS --output_dir $OUT_SAMPLES"
else
  bash "$PIPELINE_HOME/scripts/unimate-sample.sh" --asset "$RIG_DIR" \
    --prompt "${PROMPTS[@]}" --num_repetitions "$REPS" --output_dir "$OUT_SAMPLES" 2>&1 | tail -4
fi
[ "$STOP_AFTER" = "sample" ] && { echo; echo "已停止在采样步骤"; exit 0; }

# ---------------- 5. 导出 ----------------
echo
echo "== [5/5] 导出 GLB / FBX"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] bash $PIPELINE_HOME/scripts/unimate-animate.sh $OUT_SAMPLES"
else
  bash "$PIPELINE_HOME/scripts/unimate-animate.sh" "$OUT_SAMPLES" 2>&1 | tail -2
fi

echo
echo "============================================================"
if [ "$DRY" = 0 ]; then
  echo "产物："
  echo "  canonical 资产: $RIG_DIR/$NAME.glb"
  echo "  动作特征      : $OUT_SAMPLES/motions/*.npy"
  echo "  带动画 FBX    : $OUT_SAMPLES/animated/*.fbx   <- Unity 用这个"
  echo "  骨骼预览      : $OUT_SAMPLES/animations/*_fk.mp4"
  echo ""
  echo "循环化：bash $PIPELINE_HOME/scripts/unimate-loop.sh --samples $OUT_SAMPLES --name $NAME --rig $RIG_DIR/$NAME.glb"
fi
echo "完成"