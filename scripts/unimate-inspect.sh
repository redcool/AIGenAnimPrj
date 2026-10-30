#!/bin/bash
# 骨架体检：报关节数、骨骼层级、蒙皮权重、动画。
#   bash scripts/unimate-inspect.sh --input "Arts/X Bot.fbx" --no-bones
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
exec "$PY" "$TOOLS/inspect_rig.py" "$@"
