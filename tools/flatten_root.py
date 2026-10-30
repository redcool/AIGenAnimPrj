#!/usr/bin/env python3
"""把动画的根位移拉平，做成原地动作 —— 循环动画的最后一步。

为什么需要
----------
生成的动作里，根节点是在往前走的（模型学的是"向前走"，不是"原地走"）。
直接循环会出现"最后一帧在 1.8 米外，下一帧弹回原点"。
Unity 里角色位移本来就由 CharacterController 负责，动画应该是原地的。

做法
----
读导出的带动画 FBX，找到没有父级的那根根骨（Mixamo 是 mixamorig:Hips），
按帧把它的世界位移减去一条线性斜坡（首尾相消），只动位移、不动旋转，
再导出 FBX + GLB。

用法
----
  python tools/flatten_root.py --input <出来的 animated 目录>
  python tools/flatten_root.py --input a.fbx --out b.fbx
  python tools/flatten_root.py --input <dir> --flatten-y      # 连高度一起拉平

产出
----
  <out>/<name>.fbx / .glb（同名文件已存在时加 _v2、_v3，不覆盖）
  <out>/flatten_report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re

import bpy
import numpy as np

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"


def log(msg: str) -> None:
    print(msg, flush=True)


def unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    m = re.match(r"^(.*)_v(\d+)$", root)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (root, 2)
    while os.path.exists(f"{base}_v{n}{ext}"):
        n += 1
    return f"{base}_v{n}{ext}"


def import_any(path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)


def export_any(path: str) -> None:
    if path.lower().endswith(".fbx"):
        bpy.ops.export_scene.fbx(filepath=path, use_selection=False,
                                 add_leaf_bones=False, bake_anim=True)
    else:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB",
                                  export_animations=True, export_yup=True)


def flatten(path: str, out_base: str, flatten_y: bool, formats: list) -> dict:
    import_any(path)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise SystemExit(f"{path} 里没有 armature")
    arm = arms[0]

    roots = [pb for pb in arm.pose.bones if pb.parent is None]
    if not roots:
        raise SystemExit("找不到根骨")
    root = roots[0]

    act = arm.animation_data.action if arm.animation_data else None
    if act is None:
        raise SystemExit(f"{path} 里没有动画")
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    nframes = f1 - f0 + 1

    # 逐帧读根骨世界位置
    world = []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        world.append(np.array((arm.matrix_world @ root.matrix).translation))
    world = np.array(world)

    # Blender 里 X、Y 是水平面，Z 是竖直方向；FBX 导入后角色的前进方向落在 -Y 上
    drift = world[-1] - world[0]
    if not flatten_y:
        drift[2] = 0.0        # 竖直方向的起伏保留（走路上下颠是动作的一部分）

    # 世界位移增量 -> 根骨本地位移增量（根骨的朝向常量）
    R = (arm.matrix_world @ root.bone.matrix_local).to_3x3()
    R_inv = np.array(R).T

    curves = [fc for fc in act.fcurves
              if fc.data_path == f'pose.bones["{root.name}"].location']

    moved = 0
    for fc in curves:
        axis = fc.array_index
        for kp in fc.keyframe_points:
            t = (kp.co[0] - f0) / max(1, nframes - 1)
            delta = R_inv @ (-drift * t)
            kp.co[1] += float(delta[axis])
            kp.handle_left[1] += float(delta[axis])
            kp.handle_right[1] += float(delta[axis])
            moved += 1
        fc.update()

    bpy.context.scene.frame_set(f0)
    bpy.context.view_layer.update()

    outs = []
    stem = os.path.splitext(os.path.basename(path))[0]
    for fmt in formats:
        target = unique(os.path.join(out_base, f"{stem}.{fmt}"))
        export_any(target)
        outs.append(target)

    return {"input": path, "frames": nframes, "root_bone": root.name,
            "drift_removed": [round(float(v), 4) for v in drift],
            "keyframes_moved": moved, "outputs": outs}


def main() -> None:
    ap = argparse.ArgumentParser(description="拉平根位移，把动画做成原地")
    ap.add_argument("--input", required=True, help="带动画的 FBX/GLB，或一个目录")
    ap.add_argument("--out", default=None, help="输出目录，默认 <输入>_inplace")
    ap.add_argument("--formats", default="fbx", help="逗号分隔：fbx,glb")
    ap.add_argument("--flatten-y", "--flatten-vertical", dest="flatten_y",
                    action="store_true", help="连竖直方向的漂移一起拉平（默认保留走路起伏）")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    if os.path.isdir(src):
        # 同一个动作同时有 fbx 和 glb 时只用 fbx（Unity 用 fbx，避免重复导出）
        fbx = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(src, "*.fbx"))}
        files = sorted(glob.glob(os.path.join(src, "*.fbx")))
        files += [f for f in sorted(glob.glob(os.path.join(src, "*.glb")))
                  if os.path.splitext(os.path.basename(f))[0] not in fbx]
        out_base = os.path.abspath(args.out or (src.rstrip("/\\") + "_inplace"))
    else:
        files = [src]
        out_base = os.path.abspath(args.out or (os.path.dirname(src) + "_inplace"))
    os.makedirs(out_base, exist_ok=True)
    formats = [f.strip().lstrip(".") for f in args.formats.split(",") if f.strip()]

    report = {"tool": "flatten_root", "version": __version__,
              "flatten_y": args.flatten_y, "items": []}
    for f in files:
        r = flatten(f, out_base, args.flatten_y, formats)
        report["items"].append(r)
        log(f"  {os.path.basename(f)}: {r['frames']} 帧，"
            f"去掉根位移 {r['drift_removed']}（{r['root_bone']}）")

    with open(os.path.join(out_base, "flatten_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    log("")
    log(f"输出：{out_base}")
    log(f"文件：{len(report['items'])} 个 {formats}")


if __name__ == "__main__":
    main()