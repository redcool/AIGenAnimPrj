#!/usr/bin/env python3
"""模型闭环：让 UniMate 自己把动作生成成一个能首尾相接的循环。

对上游的依赖全部在 tools/unimate_api.py 里，这个文件只做命令行和文件读写。

做法
----
1. 读采样目录里的 .npy（已反归一化），交给 Session 归一化回模型空间；
2. 末 N 帧钉成「从首帧往回外推」的轨迹：
       x[T-1] = x[0]
       x[T-2] = x[0] - (x[1] - x[0])
   这样首尾不仅姿势相同，速度也接得上，收尾不会急停；
3. 替换式采样（RePaint / flow matching 解析插值）重算中间；
4. 反归一化存回，默认丢掉重复的最后一帧。

根节点位移仍由 tools/flatten_root.py 在导出后处理（模型不保证原地）。

用法
----
  python tools/loop_close.py --samples <采样目录> --asset <rig 目录>
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np

import pipeline_config as cfg


def log(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser(description="用模型自己把动作闭环")
    ap.add_argument("--samples", required=True, help="输入采样目录（含 motions/ 和 manifest.json）")
    ap.add_argument("--out", default=None, help="输出目录，默认 <samples>_closed")
    ap.add_argument("--asset", required=True, help="rig_preprocess 产物目录（建 cond 用）")
    ap.add_argument("--exp-dir", default=None, help="权重目录，默认取 config.env 的 UNIMATE_EXP")
    ap.add_argument("--only", default=None, help="只处理文件名含此子串的动作")
    ap.add_argument("--pin-tail", type=int, default=2,
                    help="钉住末 N 帧（默认 2：位置 + 速度都约束）")
    ap.add_argument("--num-steps", type=int, default=50)
    ap.add_argument("--cfg-scale", type=float, default=None)
    ap.add_argument("--no-keep-first", action="store_true")
    ap.add_argument("--keep-last", action="store_true", help="保留重复的最后一帧")
    args = ap.parse_args()

    home = cfg.unimate_home()
    exp_dir = os.path.abspath(args.exp_dir) if args.exp_dir else str(cfg.exp_dir())
    asset_dir = os.path.abspath(args.asset)

    samples_dir = os.path.abspath(args.samples)
    out_dir = os.path.abspath(args.out or (samples_dir.rstrip("/") + "_closed"))
    motions_in = os.path.join(samples_dir, "motions")
    motions_out = os.path.join(out_dir, "motions")
    if not os.path.isdir(motions_in):
        raise SystemExit("找不到 %s" % motions_in)
    os.makedirs(motions_out, exist_ok=True)

    manifest = {}
    mpath = os.path.join(samples_dir, "manifest.json")
    if os.path.isfile(mpath):
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)

    cfg.check_pinned_version(home)

    # UniMate 内部有相对路径依赖，bridge 会把 cwd 切到仓库根；
    # 所以这里先把要用的路径都转成绝对路径。
    from unimate_api import Session

    log("UniMate   : %s" % home)
    log("权重      : %s" % exp_dir)
    log("骨架      : %s" % asset_dir)
    session = Session(exp_dir=exp_dir, asset_dir=asset_dir,
                      home=str(home), cfg_scale=args.cfg_scale)
    log("object_type: %s   checkpoint: %s   cfg=%.1f"
        % (session.object_type, os.path.basename(session.model_path), session.cfg_scale))

    files = sorted(f for f in os.listdir(motions_in) if f.endswith(".npy"))
    if args.only:
        files = [f for f in files if args.only in f]
    if not files:
        raise SystemExit("没有匹配的动作文件")

    report = {"tool": "loop_close", "version": cfg.version(),
              "unimate_home": str(home), "exp_dir": exp_dir, "asset": asset_dir,
              "cfg_scale": session.cfg_scale, "num_steps": args.num_steps,
              "pin_tail": args.pin_tail, "items": []}
    new_samples = {}

    for name in files:
        x = np.load(os.path.join(motions_in, name)).astype(np.float32)
        prompt = manifest.get("samples", {}).get(name, {}).get(
            "prompt", "An object stands still.")

        m, info = session.close_loop(
            x, prompt, pin_tail=args.pin_tail, num_steps=args.num_steps,
            keep_first=not args.no_keep_first, drop_last=not args.keep_last)

        seam_before = float(np.linalg.norm(x[-1, :, 3:9] - x[0, :, 3:9]))
        seam_after = float(np.linalg.norm(m[-1, :, 3:9] - m[0, :, 3:9]))

        np.save(os.path.join(motions_out, name), m)
        if name in manifest.get("samples", {}):
            new_samples[name] = manifest["samples"][name]

        report["items"].append({
            "file": name, "prompt": prompt,
            "frames_in": info["frames_in"], "frames_out": info["frames_out"],
            "pin_frames": info["pin_frames"],
            "seam_before": round(seam_before, 4),
            "seam_after": round(seam_after, 4),
            "improved": seam_after < seam_before,
        })
        log("  %s" % name)
        log("    %d 帧 -> %d 帧，接缝 %.4f -> %.4f %s"
            % (info["frames_in"], info["frames_out"], seam_before, seam_after,
               "（改善）" if seam_after < seam_before else "（没改善）"))

    session.close()

    if manifest:
        manifest = dict(manifest)
        manifest["samples"] = new_samples or manifest.get("samples", {})
        manifest["closed_from"] = samples_dir
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "loop_close_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log("")
    log("输出：%s" % out_dir)


if __name__ == "__main__":
    main()