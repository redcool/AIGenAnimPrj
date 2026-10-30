# AIGenAnimPrj

把 [UniMate](https://github.com/Friedrich-M/UniMate)（文本 → 任意骨架动作）做成一条可复用的动画产线：
**体检 → 精简 → 打标签 → 采样 → 循环化 → 导出 Unity 能吃的 FBX**。

本工程**不修改 UniMate**，只把它当固定版本的依赖。所有对上游内部函数的调用都收在
```tools/unimate_api.py``` 一个文件里，上游升级只改那一个文件。

## 两条铁律

1. UniMate 是**只读依赖**。要改它就去 fork，另开的补丁不放进这里。
2. 临时文件一律进 ```tmp/```，删掉的文件进 ```.trash/```，同名文件不覆盖（自动加 ```_v2```）。

## 快速开始

`````````bash
# 1. 配置（config.env 不入库）
cp config.example.env config.env
#    改三个值：UNIMATE_HOME / UNIMATE_PYTHON / UNIMATE_EXP

# 2. 自检
bash setup.sh

# 3. 看看模型有几根关节
bash scripts/unimate-inspect.sh --input /path/to/model.fbx --no-bones

# 4. 一条龙：体检 -> 精简 -> 打标签 -> 采样 -> 导出
bash scripts/unimate-pipeline.sh --input /path/to/model.fbx --reps 3

# 5. 循环化 + 打包 Unity
bash scripts/unimate-loop.sh --samples <采样目录> --name <资产名> --rig <资产.glb>
`````````

Windows 上通过 WSL 调：

`````````powershell
wsl -e bash /mnt/h/..../AIGenAnimPrj/scripts/unimate-pipeline.sh --input "..."
`````````

## 目录

`````````
AIGenAnimPrj/
├── scripts/     命令行入口（bash）
├── tools/       实际干活的 Python
│   ├── pipeline_config.py   读 config.env、解析路径、版本校验
│   ├── unimate_api.py       唯一 import UniMate 内部的地方
│   ├── inspect_rig.py       骨架体检
│   ├── simplify_rig.py      骨架精简（Mixamo 65 -> 22 等）
│   ├── make_loop.py         起点 + 周期一起搜，剪切 + 接缝淡化
│   ├── loop_close.py        模型闭环（让模型把末帧收回首帧）
│   ├── flatten_root.py      拉平根位移，变原地动作
│   └── bundle_unity.py      整理成 Unity 目录 + 导入说明
├── docs/        运行记录（含本机踩过的坑）
├── tmp/         临时文件（不入库）
└── config.example.env
`````````

## 循环化：两条路线

模型生成的是固定 60 帧、起点随机的片段，首尾接不上，而且根节点在往前走。

| 动作类型 | 路线 | 实测接缝（1.0 = 和普通一步一样） |
|---|---|---|
| 走 / 跑（有周期） | ```make_loop.py```：起点 + 周期一起搜，切出来 | 0.62 ~ 1.10 |
| 待机（本来没周期） | ```loop_close.py```：钉末 2 帧，模型重算中间 | 1.36 ~ 2.21 |
| 都要 | ```flatten_root.py```：拉平根位移，位移交给引擎 | — |

`````````bash
# 走/跑
bash scripts/unimate-loop.sh --samples <dir> --name X_Bot --rig <rig.glb>

# 待机
bash scripts/unimate-loop.sh --samples <dir> --name X_Bot --rig <rig.glb> --close
`````````

关键点：**循环起点不一定在第 0 帧**。只在第 0 帧找周期会漏掉一半的片段；
同时搜起点和周期、并且把「下一帧是否也接得上」算进代价，才能既接姿势又接速度。

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| Python | 3.10 | pip 的 ```bpy``` 只有 cp310 轮子 |
| bpy | 4.0.0 | Blender 作为 Python 模块，导出 GLB/FBX 用 |
| torch | 与本机 GPU 匹配 | RTX 5090 是 sm_120，需要 cu128（仓库默认的 cu124 跑不了） |
| 磁盘 | 权重约 2 GB | 通用 1.2 GB + 人体专用 0.73 GB |

网络注意（本机实测）：```download.pytorch.org``` 不通时用镜像；HuggingFace 要设
```HF_HUB_DISABLE_XET=1```（xet 后端会挂住）；pip 太慢就换 ```uv```。
细节见 ```docs/快速上手.md```。

## 已知限制

- 关节数上限 71（人体专用权重固定 22）。超了必须先精简。
- 动作是**原地**的，位移交给 CharacterController。
- 没有脚部 IK，脚底可能滑动。
- 循环只保证姿势和速度接得上，**不保证步态周期正确**。
- 关节标签靠规则 / LLM，异常绑定可能标错，必须看 ```preview.png``` 和 ```REVIEW.md```。

## 版本

见 ```VERSION``` 和 ```CHANGELOG.md```。版本号规则：x.y 由人决定，z 大功能、w 小改动由 agent 维护。

## 许可与致谢

本工程代码 MIT（见 ```LICENSE```）。

底层 [UniMate](https://github.com/Friedrich-M/UniMate) 代码 MIT，但其**权重为 CC BY-NC 4.0（不可商用）**，
训练数据受 Mixamo / Objaverse / Truebones 各自条款约束。商用前请自行处理授权。
