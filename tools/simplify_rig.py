#!/usr/bin/env python3
"""骨架精简：把超限的绑定骨架削到 UniMate 能吃的关节数，并保住蒙皮权重。

用途
----
UniMate 的模型最多吃 71 个关节（训练时最多 70）。Mixamo 原始绑定是 65 根，
能直接进；但带多节手指、扭曲骨、表情骨的角色（MetaHuman 之类）会超。
本脚本按规则删骨，并把被删骨头上的蒙皮权重**合并到最近的保留祖先**，
所以删完之后网格不会因为"顶点没有骨头驱动"而撕裂。

三种模式
--------
mixamo : 只保留 Mixamo 的 22 根核心骨（= UniML3D 训练集里的形态）。最常见。
drop   : 删掉匹配 --drop 正则的骨头，其余保留。
keep   : 只保留匹配 --keep 正则的骨头，以及它们的祖先链。

用法
----
  python tools/simplify_rig.py --input "Arts/X Bot.fbx"
  python tools/simplify_rig.py --input a.glb --mode drop --drop "Twist|Helper|Facial"
  python tools/simplify_rig.py --input a.fbx --mode keep --keep "Hips|Spine|Arm|Leg|Head|Neck"

产出
----
  <stem>_simplified.glb        精简后的资产（默认 glb，可 --format fbx|both）
  <stem>_simplified.report.json  报告：删了什么、权重并到了哪、剩下几根、有没有漏权重

作者约定：脚本不覆盖输入文件；默认输出到输入文件同目录。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import bpy

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"

# UniML3D 训练集里 Mixamo 的 22 根核心骨（去掉了 40 根手指和 3 根 End 骨）。
# 名字不带 mixamorig: 前缀，比较时先剥前缀。
MIXAMO_CORE = [
    "Hips",
    "Spine", "Spine1", "Spine2",
    "Neck", "Head",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
    "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase",
]

MAX_JOINTS_DEFAULT = 71


def base_name(bone_name: str) -> str:
    """去掉 mixamorig: 之类的命名空间前缀。"""
    return bone_name.split(":")[-1]


def unique_path(path: str) -> str:
    """同名文件不覆盖：已存在就加 _v2、_v3……（工程纪律第 4 条）。"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    m = re.match(r"^(.*)_v(\d+)$", root)
    if m:
        root, n = m.group(1), int(m.group(2)) + 1
    else:
        n = 2
    while os.path.exists(f"{root}_v{n}{ext}"):
        n += 1
    return f"{root}_v{n}{ext}"


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #
def import_asset(path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    low = path.lower()
    if low.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif low.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise SystemExit(f"不支持的格式：{path}（要 .fbx / .glb / .gltf）")


def find_armature():
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise SystemExit("导入后没有找到 armature，无法精简")
    if len(arms) > 1:
        log(f"注意：有 {len(arms)} 个 armature，只用第一个 {arms[0].name}")
    return arms[0]


# --------------------------------------------------------------------------- #
# 决定删谁
# --------------------------------------------------------------------------- #
def decide_drops(arm, mode: str, patterns) -> list[str]:
    names = [b.name for b in arm.data.bones]

    if mode == "mixamo":
        keep = set(MIXAMO_CORE)
        present = {base_name(n) for n in names}
        missing = [k for k in MIXAMO_CORE if k not in present]
        if missing:
            raise SystemExit(
                "这不是标准的 Mixamo 绑定，缺失核心骨：" + ", ".join(missing) +
                "\n  → 若是自己的骨架，用 --mode drop/keep 指定规则"
            )
        return [n for n in names if base_name(n) not in keep]

    if mode == "drop":
        rx = [re.compile(p) for p in patterns]
        return [n for n in names if any(r.search(n) for r in rx)]

    if mode == "keep":
        rx = [re.compile(p) for p in patterns]
        keep = {n for n in names if any(r.search(n) for r in rx)}
        # 祖先必须留下，否则子骨没有父级
        for n in list(keep):
            p = arm.data.bones[n].parent
            while p is not None:
                keep.add(p.name)
                p = p.parent
        return [n for n in names if n not in keep]

    raise SystemExit(f"未知 mode：{mode}")


def merge_target(arm, bone_name: str, dropped: set[str]) -> str | None:
    """被删骨头最近的保留祖先；一路到根都没有则返回 None。"""
    p = arm.data.bones[bone_name].parent
    while p is not None:
        if p.name not in dropped:
            return p.name
        p = p.parent
    return None


# --------------------------------------------------------------------------- #
# 合并蒙皮权重
# --------------------------------------------------------------------------- #
def merge_weights(meshes, weight_map: dict[str, str]) -> dict:
    """把 weight_map（被删骨 → 保留祖先）里的权重并到祖先上。

    返回每个 mesh 的统计。必须在删骨之前调用。
    """
    stats = []
    for obj in meshes:
        vgs = obj.vertex_groups
        drop_idx_to_target = {}
        for d, t in weight_map.items():
            if d in vgs and t in vgs:
                drop_idx_to_target[vgs[d].index] = vgs[t].index

        if not drop_idx_to_target:
            stats.append({"mesh": obj.name, "merged_groups": 0,
                          "verts_touched": 0, "verts_unweighted": 0})
            continue

        # 1) 读：算每个顶点在各目标组上应该拿到的总权重
        pending = {}      # (vert_index, target_group_index) -> weight
        touched = 0
        for v in obj.data.vertices:
            acc = {}
            hit = False
            for g in v.groups:
                tgt = drop_idx_to_target.get(g.group)
                if tgt is not None:
                    acc[tgt] = acc.get(tgt, 0.0) + g.weight
                    hit = True
            if hit:
                touched += 1
                for tgt, w in acc.items():
                    key = (v.index, tgt)
                    pending[key] = pending.get(key, 0.0) + w

        # 2) 写：先加权重，再删掉被删骨对应的顶点组
        for (vidx, tgt_idx), w in pending.items():
            vg = obj.vertex_groups[tgt_idx]
            old = 0.0
            for g in obj.data.vertices[vidx].groups:
                if g.group == tgt_idx:
                    old = g.weight
                    break
            vg.add([vidx], min(1.0, old + w), "REPLACE")

        for d in weight_map:
            if d in vgs:
                vgs.remove(vgs[d])

        # 3) 检查：有没有顶点一根骨头都不剩
        unweighted = 0
        for v in obj.data.vertices:
            if not any(g.weight > 1e-6 for g in v.groups):
                unweighted += 1

        stats.append({"mesh": obj.name,
                      "merged_groups": len(drop_idx_to_target),
                      "verts_touched": touched,
                      "verts_unweighted": unweighted})
    return {"meshes": stats}


# --------------------------------------------------------------------------- #
# 删骨
# --------------------------------------------------------------------------- #
def delete_bones(arm, drops: list[str]) -> None:
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    # 从叶子往根删，避免删父骨时牵连子骨
    depth = {}
    for name in drops:
        d, p = 0, arm.data.bones[name].parent
        while p is not None:
            d += 1
            p = p.parent
        depth[name] = d
    for name in sorted(drops, key=lambda n: depth[n], reverse=True):
        eb = arm.data.edit_bones.get(name)
        if eb is not None:
            arm.data.edit_bones.remove(eb)
    bpy.ops.object.mode_set(mode="OBJECT")


# --------------------------------------------------------------------------- #
# 清掉动作里指向已删骨头的通道
# --------------------------------------------------------------------------- #
def prune_action_channels(arm, drops: list[str]) -> int:
    """删掉动作中指向已删骨的 F-Curve，避免导出时刷一堆 not found 警告。"""
    ad = arm.animation_data
    if ad is None or ad.action is None:
        return 0
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    removed = 0
    for fc in list(ad.action.fcurves):
        m = pattern.search(fc.data_path)
        if m and m.group(1) in set(drops):
            ad.action.fcurves.remove(fc)
            removed += 1
    return removed


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def export(out_path: str, animations: bool) -> None:
    low = out_path.lower()
    if low.endswith(".glb") or low.endswith(".gltf"):
        bpy.ops.export_scene.gltf(
            filepath=out_path,
            export_format="GLB" if low.endswith(".glb") else "GLTF_SEPARATE",
            export_animations=animations,
            export_yup=True,
        )
    elif low.endswith(".fbx"):
        bpy.ops.export_scene.fbx(
            filepath=out_path,
            use_selection=False,
            add_leaf_bones=False,      # 关键：否则会凭空多出 End 骨，白删
            bake_anim=animations,
        )
    else:
        raise SystemExit(f"不支持的输出格式：{out_path}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="把绑定骨架削到 UniMate 能吃的关节数")
    ap.add_argument("--input", required=True, help="输入 .fbx / .glb / .gltf")
    ap.add_argument("--output", default=None,
                    help="输出文件；默认 <输入目录>/<stem>_simplified.glb")
    ap.add_argument("--format", default="glb", choices=["glb", "fbx", "both"])
    ap.add_argument("--mode", default="mixamo", choices=["mixamo", "drop", "keep"])
    ap.add_argument("--drop", action="append", default=[],
                    help="mode=drop 时删除匹配此正则的骨（可重复）")
    ap.add_argument("--keep", action="append", default=[],
                    help="mode=keep 时保留匹配此正则的骨及其祖先（可重复）")
    ap.add_argument("--max-joints", type=int, default=MAX_JOINTS_DEFAULT,
                    help=f"删完还超这个数就报错（默认 {MAX_JOINTS_DEFAULT}）")
    ap.add_argument("--no-animation", action="store_true", help="导出时不带动画")
    ap.add_argument("--report", default=None, help="报告 JSON 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不导出")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    if not os.path.isfile(src):
        raise SystemExit(f"找不到输入文件：{src}")

    stem = os.path.splitext(os.path.basename(src))[0]
    # 文件名里的空格 / 连字符换成下划线：后面一堆 shell 命令要用到这个名字
    safe = re.sub(r"[-\s\[\]?*]+", "_", stem).strip("_") or "asset"
    out_dir = os.path.dirname(src)
    if args.output:
        outputs = [os.path.abspath(args.output)]
    else:
        outs = []
        if args.format in ("glb", "both"):
            outs.append(os.path.join(out_dir, f"{safe}_simplified.glb"))
        if args.format in ("fbx", "both"):
            outs.append(os.path.join(out_dir, f"{safe}_simplified.fbx"))
        outputs = outs
    outputs = [unique_path(p) for p in outputs]

    log(f"== 读取 {src}")
    import_asset(src)
    arm = find_armature()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    bones_before = [b.name for b in arm.data.bones]

    log(f"   armature: {arm.name}  骨头 {len(bones_before)} 根  网格 {len(meshes)} 个")

    drops = decide_drops(arm, args.mode, args.drop if args.mode == "drop" else args.keep)
    dropped = set(drops)
    kept = [n for n in bones_before if n not in dropped]

    if not drops:
        log("== 没有需要删的骨头；原样导出（仍会重写一遍文件）")

    if len(kept) > args.max_joints:
        raise SystemExit(
            f"删完还剩 {len(kept)} 根，超过上限 {args.max_joints}。\n"
            f"  保留：{', '.join(kept)}\n"
            "  → 放宽规则（例如再加 --drop 匹配手指/扭曲骨），或改用 --mode keep"
        )

    # 权重合并计划（删骨前必须做完）
    wmap = {}
    no_target = []
    for n in drops:
        t = merge_target(arm, n, dropped)
        if t is None:
            no_target.append(n)
        else:
            wmap[n] = t
    if no_target:
        log(f"   注意：这些骨头的祖先链上没有任何保留骨，权重会丢失：{no_target}")

    log(f"== 计划：删 {len(drops)} 根，留 {len(kept)} 根")
    for n in drops:
        log(f"   - {n}" + (f"   （权重并入 {wmap[n]}）" if n in wmap else ""))

    weight_stats = merge_weights(meshes, wmap)
    delete_bones(arm, drops)
    pruned = prune_action_channels(arm, drops)
    if pruned:
        log(f"   清掉动作里 {pruned} 条指向已删骨的通道")

    # 删骨后复查：动作里残留的被删骨通道会被 Blender 忽略，这里不处理
    log("== 权重合并结果")
    for s in weight_stats["meshes"]:
        log(f"   {s['mesh']}: 并组 {s['merged_groups']} 个，影响顶点 {s['verts_touched']}，"
            f"无权重顶点 {s['verts_unweighted']}")

    report = {
        "tool": "simplify_rig",
        "version": __version__,
        "input": src,
        "armature": arm.name,
        "mode": args.mode,
        "bones_before": len(bones_before),
        "bones_after": len(kept),
        "dropped": drops,
        "weight_merge": wmap,
        "kept": kept,
        "weight_stats": weight_stats,
        "outputs": outputs,
        "pruned_action_channels": pruned,
        "max_joints": args.max_joints,
        "fits": len(kept) <= args.max_joints,
    }

    if args.dry_run:
        log("== dry-run：不导出")
    else:
        for out in outputs:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            export(out, animations=not args.no_animation)
            log(f"== 已写出 {out}")

    rep_path = args.report or (os.path.splitext(outputs[0])[0] + ".report.json")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log(f"== 报告 {rep_path}")

    bad = [s for s in weight_stats["meshes"] if s["verts_unweighted"] > 0]
    if bad:
        log("   注意：有顶点失去全部权重，动画时可能不跟随骨架；检查删除规则")
    else:
        log("   所有顶点都还有骨骼权重")

    if not args.dry_run:
        log("")
        log("下一步（在 UniMate 仓库根目录）：")
        log(f"  python -m data_process.rig_preprocess run --input {outputs[0]} "
            f"--output_dir outputs/rig/{safe} --name {safe}")


if __name__ == "__main__":
    main()