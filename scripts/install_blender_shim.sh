#!/bin/bash
# 在 UniMate 的 Python 环境里装一个 blender 假命令。
#
# 为什么需要：UniMate 的 data_process/scripts/run_animate_motion.sh 写死了
#   blender -b --python-exit-code 1 -P data_process/mesh_animation/animate_motion.py -- ...
# 而我们没有装 Blender 本体，用的是 pip 的 bpy 模块（Blender 4.0 作为 Python 库）。
# 这个假命令把上面的调用翻译成 "用环境里的 python 直接跑那个脚本"。
#
#   bash scripts/install_blender_shim.sh          # 安装 / 覆盖
#   bash scripts/install_blender_shim.sh --check  # 只检查
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"

TARGET="$(dirname "$PY")/blender"

if [ "${1:-}" = "--check" ]; then
  if [ -x "$TARGET" ]; then
    echo "已安装: $TARGET"
    head -2 "$TARGET" | tail -1
  else
    echo "未安装。跑 bash scripts/install_blender_shim.sh"
    exit 1
  fi
  exit 0
fi

# 如果 PATH 里已经有真正的 Blender，先提醒
REAL="$(command -v blender 2>/dev/null || true)"
if [ -n "$REAL" ] && [ "$REAL" != "$TARGET" ]; then
  echo "注意：PATH 里已有 blender（$REAL），不会被覆盖；"
  echo "      UniMate 的脚本会优先用到它。要强制用 bpy 模块，把它移出 PATH。"
fi

cat > "$TARGET" <<EOS
#!/bin/bash
# 自动生成（AIGenAnimPrj/scripts/install_blender_shim.sh），不要手改。
# 把 blender -b -P script.py -- args 翻译成用 bpy 模块的 python 直接跑脚本。
PY="${PY}"
script=""; args=()
while [ \$# -gt 0 ]; do
  case "\$1" in
    -P|--python) script="\$2"; shift 2 ;;
    --python-exit-code|--python-text) shift 2 ;;
    --) shift; args=("\$@"); break ;;
    *) shift ;;
  esac
done
[ -n "\$script" ] || { echo "blender shim: 没有 -P 脚本" >&2; exit 2; }
exec "\$PY" "\$script" "\${args[@]}"
EOS
chmod +x "$TARGET"
echo "已安装: $TARGET"
echo "把它所在目录放进 PATH 就能用（_env.sh 会自动加）：$(dirname "$TARGET")"
