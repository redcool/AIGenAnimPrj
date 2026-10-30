#!/bin/bash
# 环境自检：缺什么说什么。首次使用先跑这个。
#   bash setup.sh
set -uo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/scripts/_env.sh"

fail=0
ok()   { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [缺少] %s\n' "$1"; fail=1; }

echo "== 配置"
echo "  工程目录 : $PIPELINE_HOME"
echo "  UniMate  : $UNIMATE_HOME"
echo "  Python   : $PY"
echo "  权重     : $EXP_DIR"
echo "  采样根   : $SAMPLES_HOME"

echo
echo "== 依赖检查"
[ -d "$UNIMATE_HOME/unimate" ] && ok "UniMate 仓库" || bad "UniMate 仓库（检查 UNIMATE_HOME）"
[ -x "$PY" ] && ok "Python 解释器" || bad "Python 解释器（检查 UNIMATE_PYTHON）"

"$PY" - <<'EOF' || fail=1
import sys
def check(name, fn):
    try:
        detail = fn()
        print("  [ok]   %s %s" % (name, detail or ""))
    except Exception as e:
        print("  [缺少] %s (%s)" % (name, e)); sys.exit(1)

check("numpy", lambda: __import__("numpy").__version__)
check("bpy", lambda: __import__("bpy").app.version_string)
check("torch", lambda: __import__("torch").__version__)

def cuda():
    import torch
    assert torch.cuda.is_available(), "CUDA 不可用"
    return "%s cap=%s" % (torch.cuda.get_device_name(0), torch.cuda.get_device_cuda_capability(0)
                          if hasattr(torch.cuda, "get_device_cuda_capability")
                          else torch.cuda.get_device_capability(0))
check("CUDA", cuda)
EOF

echo
echo "== UniMate 版本"
"$PY" -c "
import sys, pathlib
sys.path.insert(0, '$PIPELINE_HOME/tools')
import pipeline_config as c
c.check_pinned_version(pathlib.Path('$UNIMATE_HOME'))
print('  当前 commit: %s' % c.check_pinned_version(pathlib.Path('$UNIMATE_HOME')))
" 2>/dev/null || true

echo
if [ "$fail" = 0 ]; then
  echo "自检通过。下一步："
  echo "  bash scripts/unimate-inspect.sh --input <你的模型.fbx>"
  echo "  bash scripts/unimate-pipeline.sh --input <你的模型.fbx>"
else
  echo "有项目未通过，按提示补齐。"
  exit 1
fi
