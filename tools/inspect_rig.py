#!/usr/bin/env python3
"""骨架体检：读一个 FBX / GLB / glTF，报出关节数、骨骼层级、蒙皮权重和动画。

回答三个问题：
  1. 这个骨架有多少关节？（UniMate 上限 71，Mixamo 原始是 65，UniML3D 版是 22）
  2. 每根骨头真的带蒙皮权重吗？（不带的骨头删掉不影响网格）
  3. 有没有动画？几个 action？

用法：
  python tools/inspect_rig.py --input "Arts/X Bot.fbx"
  python tools/inspect_rig.py --input a.glb --json out.json     # 存成 JSON
  python tools/inspect_rig.py --input a.fbx --no-bones          # 只看汇总

作者约定：只读，不改输入文件。
"""

from __future__ import annotations

import argparse
import json
import sys

import bpy

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"


def log(msg: str) -> None:
    print(msg, flush=True)


def import_asset(path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    low = path.lower()
    if low.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif low.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise SystemExit(f"不支持的格式：{path}（要 .fbx / .glb / .gltf）")


def main() -> None:
    ap = argparse.ArgumentParser(description="报出一个绑定资产的骨架、权重和动画信息")
    ap.add_argument("--input", required=True)
    ap.add_argument("--json", default=None, help="把结果另存为 JSON")
    ap.add_argument("--no-bones", action="store_true", help="不逐根打印骨头")
    args = ap.parse_args()

    import_asset(args.input)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms:
        raise SystemExit("没有 armature，这不是一个绑定角色")

    arm = arms[0]
    bone_names = [b.name for b in arm.data.bones]

    # 绑定状态：网格上有没有 armature 修改器、有没有顶点组
    skinned = []
    for m in meshes:
        has_mod = any(md.type == "ARMATURE" for md in m.modifiers)
        skinned.append({"name": m.name, "verts": len(m.data.vertices),
                        "armature_modifier": has_mod,
                        "vertex_groups": len(m.vertex_groups)})

    # 哪些骨头真的有顶点权重
    weighted = set()
    for m in meshes:
        for v in m.data.vertices:
            for g in v.groups:
                if g.weight > 1e-6:
                    weighted.add(m.vertex_groups[g.group].name)
    unweighted = [n for n in bone_names if n not in weighted]

    # 有没有顶点完全没权重
    orphan_verts = 0
    for m in meshes:
        for v in m.data.vertices:
            if not any(g.weight > 1e-6 for g in v.groups):
                orphan_verts += 1

    result = {
        "input": args.input,
        "armature": arm.name,
        "armature_count": len(arms),
        "armatures": [a.name for a in arms],
        "skinned_meshes": skinned,
        "bone_count": len(bone_names),
        "meshes": [{"name": m.name, "verts": len(m.data.vertices),
                    "vertex_groups": len(m.vertex_groups)} for m in meshes],
        "actions": [a.name for a in bpy.data.actions],
        "bones_with_weight": len(weighted),
        "bones_without_weight": unweighted,
        "vertices_without_any_weight": orphan_verts,
        "bones": [{"name": b.name,
                   "parent": b.parent.name if b.parent else None}
                  for b in arm.data.bones],
    }

    log(f"文件      : {args.input}")
    log(f"armature  : {arm.name}" + (f"（共 {len(arms)} 个，只用第一个）" if len(arms) > 1 else ""))
    if len(arms) > 1:
        log(f"  ↑ 注意：UniMate 要求一个文件一套骨架，多余的要先合并或删掉")
    log(f"关节数    : {len(bone_names)}"
        f"   （UniMate 上限 71 / Mixamo 原始 65 / UniML3D 版 22）")
    log(f"网格      : " + ", ".join(f"{m['name']}({m['verts']}顶/{m['vertex_groups']}组)"
                                    for m in result["meshes"]))
    # 按主网格（顶点最多那个）判断是否绑定，顺带列出没绑的零碎对象
    main_mesh = max(skinned, key=lambda s: s["verts"]) if skinned else None
    main_ok = bool(main_mesh and main_mesh["armature_modifier"] and main_mesh["vertex_groups"])
    unbound = [s["name"] for s in skinned
               if not (s["armature_modifier"] and s["vertex_groups"])]
    log(f"蒙皮      : " + ("已绑定" if main_ok else "未绑定（主网格缺 armature 修改器或顶点组）"))
    if main_ok and unbound:
        log(f"            附带未绑定对象: {unbound}（不影响，导出时会被丢掉）")
    log(f"动作      : {result['actions'] or '无'}")
    log(f"带权重的骨: {len(weighted)} / {len(bone_names)}")
    if unweighted:
        log(f"无权重骨  : {unweighted}")
    log(f"无权重顶点: {orphan_verts}" + ("   ← 有顶点不跟骨架动，检查一下" if orphan_verts else ""))

    if not args.no_bones:
        log("")
        log("骨骼层级：")
        for i, b in enumerate(arm.data.bones):
            log(f"  [{i:3d}] {b.name}  parent={b.parent.name if b.parent else None}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        log(f"\n已写出 {args.json}")


if __name__ == "__main__":
    main()