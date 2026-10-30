#!/bin/bash
# 骨架精简：把超限的绑定骨架削到 UniMate 能吃的关节数（默认 Mixamo 22 根核心骨）。
#   bash scripts/unimate-simplify.sh --input "Arts/X Bot.fbx"
#   bash scripts/unimate-simplify.sh --input a.glb --mode drop --drop "Twist|Helper"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
exec "$PY" "$TOOLS/simplify_rig.py" "$@"
