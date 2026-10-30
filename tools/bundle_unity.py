#!/usr/bin/env python3
"""把处理好的动作整理成 Unity 能直接拖进去的目录结构。

输入是采样目录（认 motions/ 里的文件名）和已经原地化的 FBX 目录，
输出：角色 FBX + anim/<类别>_<序号>.fbx + README-Unity.md（含循环质量表）。

用法
----
  python tools/bundle_unity.py --samples UniMate/outputs/samples/X_Bot_locomotion \
      --animated UniMate/outputs/samples/X_Bot_locomotion_loop/animated_inplace \
      --rig UniMate/outputs/rig/X_Bot/X_Bot.glb --name X_Bot \
      --out UniMate/outputs/samples/X_Bot_locomotion_loop/unity
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil

import bpy

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"

DEFAULT_MAP = {
    "stands_still": "idle",
    "walks_forward": "walk",
    "runs_forward": "run",
}
FENCE = "```"


def log(msg: str) -> None:
    print(msg, flush=True)


def make_character_fbx(rig_path: str, out_path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if rig_path.lower().endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=rig_path)
    else:
        bpy.ops.import_scene.fbx(filepath=rig_path)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and len(o.data.vertices) < 10]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.export_scene.fbx(filepath=out_path, use_selection=False,
                             add_leaf_bones=False, bake_anim=False)


def classify(name: str, mapping: dict) -> tuple:
    rep = re.search(r"-rep_(\d)", name)
    idx = rep.group(1) if rep else "0"
    low = name.lower()
    for key, cls in mapping.items():
        if key.lower() in low:
            return cls, idx
    stem = os.path.splitext(name)[0]
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")[:24] or "motion", idx


def main() -> None:
    ap = argparse.ArgumentParser(description="整理 Unity 导入用的目录")
    ap.add_argument("--samples", required=True)
    ap.add_argument("--animated", required=True)
    ap.add_argument("--rig", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--map", default=None, help='类别映射，如 "stands_still=idle,walks_forward=walk"')
    args = ap.parse_args()

    samples = os.path.abspath(args.samples)
    animated = os.path.abspath(args.animated)
    out = os.path.abspath(args.out or os.path.join(os.path.dirname(samples), "unity"))
    anim_out = os.path.join(out, "anim")
    os.makedirs(anim_out, exist_ok=True)

    mapping = dict(DEFAULT_MAP)
    if args.map:
        mapping = {}
        for pair in args.map.split(","):
            k, _, v = pair.partition("=")
            if k.strip() and v.strip():
                mapping[k.strip()] = v.strip()

    char_fbx = os.path.join(out, args.name + "_character.fbx")
    make_character_fbx(os.path.abspath(args.rig), char_fbx)
    log("角色: %s (%.2f MB)" % (char_fbx, os.path.getsize(char_fbx) / 1e6))

    rows = []
    for f in sorted(glob.glob(os.path.join(animated, "*.fbx"))):
        cls, idx = classify(os.path.basename(f), mapping)
        dst = os.path.join(anim_out, cls + "_" + idx + ".fbx")
        shutil.copy2(f, dst)
        rows.append((cls, idx, os.path.basename(f), os.path.getsize(dst) / 1e6))
    log("动作: %d 个 -> %s" % (len(rows), anim_out))
    for cls, idx, src, mb in rows:
        log("  %s_%s.fbx (%.2f MB) <- %s" % (cls, idx, mb, src))

    quality = {}
    # 优先用和 animated/ 同级的报告（本次运行的），再退回 <samples>_loop
    for cand in (os.path.join(os.path.dirname(os.path.abspath(animated)), "loop_report.json"),
                 os.path.join(samples, "loop_report.json"),
                 os.path.join(os.path.dirname(samples), os.path.basename(samples) + "_loop", "loop_report.json")):
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as fh:
                quality = json.load(fh).get("items", {})
            break

    # 模型闭环路线没有 loop_report，改读 loop_close_report
    closed = {}
    cand2 = os.path.join(os.path.dirname(animated), "loop_close_report.json")
    if os.path.isfile(cand2):
        with open(cand2, encoding="utf-8") as fh:
            closed = {it["file"]: it for it in json.load(fh).get("items", [])}

    lines = []
    for cls, idx, src, mb in rows:
        q = quality.get(src) or quality.get(os.path.splitext(src)[0] + ".npy")
        cq = closed.get(os.path.splitext(src)[0] + ".npy")
        if cq:
            lines.append("| %s_%s.fbx | %d | %.4f -> %.4f | 模型闭环 |" % (
                cls, idx, cq["frames_out"], cq["seam_before"], cq["seam_after"]))
        elif q:
            lines.append("| %s_%s.fbx | %d | %.1f 倍（绝对 %.3f） | %s |" % (
                cls, idx, q["frames_out"], q["seam_ratio_before"],
                q.get("seam_before_abs") or 0.0, q["loop_verdict"]))
        else:
            lines.append("| %s_%s.fbx | - | - | - |" % (cls, idx))

    readme = "\n".join([
        "# Unity 导入说明（%s）" % args.name,
        "",
        "## 文件",
        "",
        FENCE,
        os.path.basename(out) + "/",
        "├── " + args.name + "_character.fbx      角色本体：骨架 + 蒙皮，无动画",
        "└── anim/                          %d 个动作（原地，已做过循环处理）" % len(rows),
        FENCE,
        "",
        "## 循环质量",
        "",
        "接缝倍数越接近 1 越好：1.0 = 和普通相邻两帧一样。",
        "",
        "| 文件 | 帧数 | 接缝 | 来源 |",
        "|---|---|---|---|",
    ] + lines + [
        "",
        "后处理路线：接缝写成「倍数（绝对值）」，倍数 = 首尾差 / 平均每帧步长，1.0 = 和普通一步一样。",
        "模型闭环路线：接缝写成「闭环前 -> 闭环后」的绝对差，越小越好。",
        "",
        "同一类动作有几个版本时，优先用倍数最小、判定最好的那条。",
        "",
        "## 导入步骤",
        "",
        "1. " + args.name + "_character.fbx 拖进 Assets：",
        "   Rig → Animation Type = Humanoid，Avatar Definition = Create From This Model → Apply。",
        "2. anim/ 下所有 FBX 拖进 Assets，逐个设：",
        "   Rig → Humanoid，Avatar Definition = Copy From Other Avatar，Source 选第 1 步的 Avatar。",
        "   Animation 页签 → 勾 Loop Time。",
        "3. Root Transform Rotation / Position(Y) / Position(XZ) 都勾 Bake Into Pose，Based Upon = Original。",
        "4. Animator 里建状态机（idle / walk / run），用 float 参数过渡。",
        "",
        "## 已知",
        "",
        "- 动作是原地（in-place）的，位移交给 CharacterController。",
        "- 判为「整段收拢」的动作结尾有一帧停顿（1/30 秒），微动看不出来；判为「建议重新采样」的最好别用。",
        "- 没有脚部 IK，脚底可能有滑动。",
        "",
    ])
    with open(os.path.join(out, "README-Unity.md"), "w", encoding="utf-8") as fh:
        fh.write(readme)
    log("说明: %s" % os.path.join(out, "README-Unity.md"))


if __name__ == "__main__":
    main()